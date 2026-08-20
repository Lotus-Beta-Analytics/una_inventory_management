# from odoo import models, fields, api
# from odoo.exceptions import UserError
#
#
# class AssignAssetWizard(models.TransientModel):
#     _name = 'assign.asset.wizard'
#     _description = 'Assign Asset Wizard'
#
#     asset_id = fields.Many2one('una.asset', string='Asset', required=True)
#     employee_id = fields.Many2one('hr.employee', string='Assign To', required=True)
#     location_id = fields.Many2one('una.location', string='Location')
#
#     def action_assign(self):
#         """Assign asset to employee"""
#         for wizard in self:
#             if not wizard.employee_id:
#                 raise UserError('Please select an employee!')
#
#             wizard.asset_id.write({
#                 'assigned_to': wizard.employee_id.id,
#                 'assigned_date': fields.Date.today(),
#                 'status': 'assigned',
#                 'current_location': wizard.location_id.id or wizard.asset_id.current_location.id,
#             })
#
#             wizard.asset_id.message_post(
#                 body=f"✅ Asset assigned to {wizard.employee_id.name}"
#             )
#
#         return {'type': 'ir.actions.act_window_close'}