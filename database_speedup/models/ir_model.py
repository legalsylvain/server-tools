# Copyright (C) 2021-Today: GRAP (<http://www.grap.coop/>)
# @author: Sylvain LE GAL (https://twitter.com/legalsylvain)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo import models


class IrModel(models.Model):
    _inherit = 'ir.model'

    def unlink(self):
        print("database_speedup::ir.model::unlink()")
        for model in self:
            # Drop SQL constrains to make the 'DROP' command faster
            self._cr.execute("""
                SELECT indexname
                FROM pg_indexes
                WHERE tablename = %s;""", (model._table,))
            for index_name in [row[0] for row in self._cr.fetchall()]:
                if not index_name.endswith("_index"):
                    self._cr.execute("""
                        DROP INDEX "%s" CASCADE;
                    """, (index_name,))
            super(IrModel, model)._unlink()
        return True
