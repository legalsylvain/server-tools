# -*- encoding: utf-8 -*-
#################################################################################
#
#    Scheduler Error Mailer module for OpenERP
#    Copyright (C) 2012-2013 Akretion (http://www.akretion.com/)
#    @author: Sébastien Beau <sebastien.beau@akretion.com>
#    @author David Beal <bealdavid@gmail.com>
#    @author Alexis de Lattre <alexis.delattre@akretion.com>
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

from openerp.osv import orm, fields
from openerp.tools.translate import _
import logging

logger = logging.getLogger(__name__)

class ir_cron(orm.Model):
    _inherit = "ir.cron"

    _columns = {
        'email_template': fields.many2one('email.template',
            'Error E-mail Template',
            help="Select the email template that will be sent when this scheduler fails."),
    }


    def _handle_callback_exception(self, cr, uid, model_name, method_name, args, job_id, job_exception):

        res = super(ir_cron, self)._handle_callback_exception(cr, uid,
            model_name, method_name, args, job_id, job_exception)

        my_cron = self.browse(cr, uid, job_id)

        if my_cron.email_template:
            # we put the job_exception in context to be able to print it inside
            # the email template
            context = {
                'job_exception': job_exception,
                'dbname': cr.dbname,
                }

            logger.debug("Sending scheduler error email with context=%s" % context)
            self.pool['email.template'].send_mail(cr, uid,
                my_cron.email_template.id, my_cron.id, force_send=True,
                context=context)

        return res


class res_users(orm.Model):
    _inherit = 'res.users'

    def test_scheduler_failure(self, cr, uid, context=None):
        """This function is used to test and debug this module"""
        raise orm.except_orm(_('Error :'), _("Task failure with UID = %d." % uid))

