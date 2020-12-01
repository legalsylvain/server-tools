# Copyright 2011-2015 Therp BV <https://therp.nl>
# Copyright 2016 Opener B.V. <https://opener.am>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
# flake8: noqa: C901

import json
import logging
import os

from odoo import fields, models
from odoo.exceptions import UserError
from odoo.modules import get_module_path
from odoo.tools import config
from odoo.tools.translate import _

from .. import compare

_logger = logging.getLogger(__name__)
_IGNORE_MODULES = ["openupgrade_records", "upgrade_analysis"]


class Apriori(object):
    def __init__(self, apriori_dict):
        for key in [
            "renamed_modules",
            "merged_modules",
            "renamed_models",
            "merged_models",
        ]:
            try:
                setattr(self, key, apriori_dict[key])
            except KeyError:
                raise UserError(
                    _("Invalid contents of apriori.json: no key '%s'") % key
                )


class UpgradeAnalysis(models.Model):
    _name = "upgrade.analysis"
    _description = "Upgrade Analyses"

    analysis_date = fields.Datetime(readonly=True)
    without_apriori = fields.Boolean(
        default=False,
        help=(
            "A file apriori.json encodes known renames of modules and models. "
            "This process expects to find it in the upgrade path. Tick this box if you "
            "Tick this box if you do not provide such a file, or if you do not wish to "
            "use it."
        ),
    )

    state = fields.Selection(
        [("draft", "draft"), ("done", "Done")], readonly=True, default="draft"
    )
    config_id = fields.Many2one(
        string="Comparison Config",
        comodel_name="upgrade.comparison.config",
        readonly=True,
        required=True,
    )

    log = fields.Text(readonly=True)
    upgrade_path = fields.Char(
        default=config.get("upgrade_path", False),
        help=(
            "The base file path to save the analyse files of Odoo modules. "
            "Default is taken from Odoo's --upgrade-path command line option. "
            "At this location, an apriori.json file must exist."
        ),
        required=True,
    )

    write_files = fields.Boolean(
        help="Write analysis files to the module directories", default=True
    )

    def _get_remote_model(self, connection, model):
        self.ensure_one()
        if model == "record":
            if float(self.config_id.version) < 14:
                return connection.env["openupgrade.record"]
            else:
                return connection.env["upgrade.record"]
        return False

    def _write_file(
        self, module_name, version, content, filename="upgrade_analysis.txt"
    ):
        module = self.env["ir.module.module"].search([("name", "=", module_name)])[0]
        if module.is_odoo_module:
            module_path = os.path.join(self.upgrade_path, module_name)
        else:
            module_path = get_module_path(module_name)
        if not module_path:
            return "ERROR: could not find module path of '%s':\n" % (module_name)
        full_path = os.path.join(module_path, "migrations", version)
        if not os.path.exists(full_path):
            try:
                os.makedirs(full_path)
            except os.error:
                return "ERROR: could not create migrations directory %s:\n" % (
                    full_path
                )
        logfile = os.path.join(full_path, filename)
        try:
            f = open(logfile, "w")
        except Exception:
            return "ERROR: could not open file %s for writing:\n" % logfile
        _logger.debug("Writing analysis to %s", logfile)
        f.write(content)
        f.close()
        return None

    def analyze(self):
        """
        Retrieve both sets of database representations,
        perform the comparison and register the resulting
        change set
        """
        self.ensure_one()
        self.write(
            {
                "analysis_date": fields.Datetime.now(),
            }
        )

        if not self.upgrade_path:
            return (
                "ERROR: no upgrade_path set when writing analysis of %s\n" % module_name
            )

        if not self.without_apriori:
            apriori_path = os.path.join(self.upgrade_path, "apriori.json")
            try:
                with open(apriori_path) as json_file:
                    apriori_dict = json.load(json_file)
            except FileNotFoundError:
                raise UserError(
                    _("Could not import apriori.json: file %s not found") % apriori_path
                )
            except ValueError:
                raise UserError(_("The contents of apriori.json is not valid json"))
            apriori = Apriori(apriori_dict)
        else:
            apriori = None

        connection = self.config_id.get_connection()
        RemoteRecord = self._get_remote_model(connection, "record")
        LocalRecord = self.env["upgrade.record"]

        # Retrieve field representations and compare
        remote_records = RemoteRecord.field_dump()
        local_records = LocalRecord.field_dump()
        res = compare.compare_sets(remote_records, local_records, apriori)

        # Retrieve xml id representations and compare
        flds = [
            "module",
            "model",
            "name",
            "noupdate",
            "prefix",
            "suffix",
            "domain",
        ]
        local_xml_records = [
            {field: record[field] for field in flds}
            for record in LocalRecord.search([("type", "=", "xmlid")])
        ]
        remote_xml_record_ids = RemoteRecord.search([("type", "=", "xmlid")])
        remote_xml_records = [
            {field: record[field] for field in flds}
            for record in RemoteRecord.read(remote_xml_record_ids, flds)
        ]
        res_xml = compare.compare_xml_sets(
            remote_xml_records, local_xml_records, apriori
        )

        # Retrieve model representations and compare
        flds = [
            "module",
            "model",
            "name",
            "model_original_module",
            "model_type",
        ]
        local_model_records = [
            {field: record[field] for field in flds}
            for record in LocalRecord.search([("type", "=", "model")])
        ]
        remote_model_record_ids = RemoteRecord.search([("type", "=", "model")])
        remote_model_records = [
            {field: record[field] for field in flds}
            for record in RemoteRecord.read(remote_model_record_ids, flds)
        ]
        res_model = compare.compare_model_sets(
            remote_model_records, local_model_records, apriori
        )

        affected_modules = sorted(
            {
                record["module"]
                for record in remote_records
                + local_records
                + remote_xml_records
                + local_xml_records
                + remote_model_records
                + local_model_records
            }
        )

        # reorder and output the result
        keys = ["general"] + affected_modules
        modules = {
            module["name"]: module
            for module in self.env["ir.module.module"].search(
                [("state", "=", "installed")]
            )
        }
        general_log = ""

        for ignore_module in _IGNORE_MODULES:
            if ignore_module in keys:
                keys.remove(ignore_module)

        for key in keys:
            contents = "---Models in module '%s'---\n" % key
            if key in res_model:
                contents += "\n".join([str(line) for line in res_model[key]])
                if res_model[key]:
                    contents += "\n"
            contents += "---Fields in module '%s'---\n" % key
            if key in res:
                contents += "\n".join([str(line) for line in sorted(res[key])])
                if res[key]:
                    contents += "\n"
            contents += "---XML records in module '%s'---\n" % key
            if key in res_xml:
                contents += "\n".join([str(line) for line in res_xml[key]])
                if res_xml[key]:
                    contents += "\n"
            if key not in res and key not in res_xml and key not in res_model:
                contents += "---nothing has changed in this module--\n"
            if key == "general":
                general_log += contents
                continue
            if compare.module_map(key, apriori) not in modules:
                general_log += (
                    "ERROR: module not in list of installed modules:\n" + contents
                )
                continue
            if key not in modules:
                # no need to log in full log the merged/renamed modules
                continue
            if self.write_files:
                error = self._write_file(key, modules[key].installed_version, contents)
                if error:
                    general_log += error
                    general_log += contents
            else:
                general_log += contents

        # Store the full log
        if self.write_files and "base" in modules:
            self._write_file(
                "base",
                modules["base"].installed_version,
                general_log,
                "upgrade_general_log.txt",
            )
        self.write(
            {
                "state": "done",
                "log": general_log,
            }
        )
