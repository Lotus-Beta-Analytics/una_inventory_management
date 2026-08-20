from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError


class UnaAssetDamageReport(models.Model):
    _name = 'una.asset.damage.report'
    _description = 'UNA Asset Damage Report'
    _rec_name = 'asset_id'
    _order = 'reported_date desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    # === BASIC FIELDS ===
    asset_id = fields.Many2one('una.asset', string='Asset', required=True)
    employee_id = fields.Many2one('hr.employee', string='Reported By', required=True)
    stock_move_id = fields.Many2one('una.stock.move', string='Stock Move')

    # === LINE MANAGER ===
    line_manager_id = fields.Many2one(
        'hr.employee',
        string='Line Manager',
        related='employee_id.parent_id',
        store=True,
        help="Employee's line manager"
    )

    # === DAMAGE DETAILS ===
    damage_description = fields.Text(string='Damage Description', required=True)
    damage_severity = fields.Selection([
        ('minor', 'Minor'),
        ('moderate', 'Moderate'),
        ('severe', 'Severe'),
        ('critical', 'Critical'),
    ], string='Damage Severity', default='minor', required=True)

    # === STATUS ===
    status = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('line_manager_approved', 'Approved by Line Manager'),
        ('admin_approved', 'Approved by Admin'),
        ('rejected', 'Rejected'),
        ('scrapped', 'Scrapped'),
    ], string='Status', default='draft', tracking=True)

    reported_date = fields.Datetime(string='Reported Date', default=fields.Datetime.now)
    submitted_date = fields.Datetime(string='Submitted Date')
    line_manager_approval_date = fields.Datetime(string='Line Manager Approval Date')
    admin_approval_date = fields.Datetime(string='Admin Approval Date')
    reviewed_date = fields.Datetime(string='Reviewed Date')
    reviewed_by = fields.Many2one('res.users', string='Reviewed By')
    rejection_reason = fields.Text(string='Rejection Reason')
    line_manager_comment = fields.Text(string='Line Manager Comment')
    admin_comment = fields.Text(string='Admin Comment')

    status_badge_class = fields.Char(
        string='Status Badge Class',
        compute='_compute_status_badge_class',
        store=False
    )

    @api.depends('status')
    def _compute_status_badge_class(self):
        for record in self:
            if record.status == 'draft':
                record.status_badge_class = 'bg-secondary'
            elif record.status == 'submitted':
                record.status_badge_class = 'bg-warning'
            elif record.status == 'line_manager_approved':
                record.status_badge_class = 'bg-info'
            elif record.status in ['admin_approved', 'scrapped']:
                record.status_badge_class = 'bg-success'
            else:
                record.status_badge_class = 'bg-danger'

    source_badge_class = fields.Char(
        string='Source Badge Class',
        compute='_compute_source_badge_class',
        store=False
    )

    @api.depends('source')
    def _compute_source_badge_class(self):
        for record in self:
            if record.source == 'portal':
                record.source_badge_class = 'bg-info'
            else:
                record.source_badge_class = 'bg-secondary'

    source = fields.Selection([
        ('portal', 'Portal'),
        ('internal', 'Internal'),
    ], string='Source', default='internal', help="Where the report was created from")

    # === COMPUTE FIELDS ===
    asset_name = fields.Char(string='Asset Name', related='asset_id.name', store=True)
    asset_tag = fields.Char(string='Asset Tag', related='asset_id.asset_tag', store=True)
    serial_number = fields.Char(string='Serial Number', related='asset_id.serial_number', store=True)
    employee_name = fields.Char(string='Employee Name', related='employee_id.name', store=True)
    line_manager_name = fields.Char(string='Line Manager Name', related='employee_id.parent_id.name', store=True)

    @api.constrains('damage_severity', 'damage_description')
    def _check_damage_severity(self):
        for rec in self:
            if rec.damage_severity == 'critical' and len(rec.damage_description or '') < 20:
                raise ValidationError(
                    'Please provide a detailed description (at least 20 characters) for critical damage!')

    # === ACTIONS ===

    def action_submit(self):
        """Submit damage report for approval"""
        for report in self:
            if report.status != 'draft':
                raise UserError('Only draft reports can be submitted!')

            report.status = 'submitted'
            report.submitted_date = fields.Datetime.now()

            # Notify line manager
            if report.line_manager_id:
                report._notify_line_manager()
            else:
                # If no line manager, notify admin directly
                report._notify_admins()

            report.message_post(body="📤 Damage report submitted for approval.")

    def action_line_manager_approve(self):
        """Line Manager approves the damage report"""
        for report in self:
            if report.status != 'submitted':
                raise UserError('Only submitted reports can be approved by Line Manager!')

            report.status = 'line_manager_approved'
            report.line_manager_approval_date = fields.Datetime.now()

            # Notify admins
            report._notify_admins()

            report.message_post(body=f"✅ Damage report approved by Line Manager: {report.line_manager_name or 'N/A'}")

    def action_line_manager_reject(self):
        """Line Manager rejects the damage report"""
        for report in self:
            if report.status != 'submitted':
                raise UserError('Only submitted reports can be rejected!')

            if not report.rejection_reason:
                raise UserError('Please provide a rejection reason!')

            report.status = 'rejected'
            report.reviewed_date = fields.Datetime.now()
            report.reviewed_by = self.env.user
            report.message_post(body=f"❌ Damage report rejected by Line Manager: {report.rejection_reason}")

    def action_admin_approve(self):
        """Admin approves the damage report for scrapping"""
        for report in self:
            if report.status not in ['submitted', 'line_manager_approved']:
                raise UserError('Only submitted or line manager approved reports can be admin approved!')

            report.status = 'admin_approved'
            report.admin_approval_date = fields.Datetime.now()
            report.reviewed_by = self.env.user

            # Confirm stock move if it exists
            if report.stock_move_id:
                if report.stock_move_id.state == 'draft':
                    report.stock_move_id.action_confirm()
                    report.message_post(
                        body=f"✅ Stock move {report.stock_move_id.reference} confirmed for scrapping asset."
                    )
                else:
                    report.message_post(
                        body=f"⚠️ Stock move {report.stock_move_id.reference} already in state: {report.stock_move_id.state}"
                    )

            # Update asset status
            report.asset_id.write({
                'status': 'scrapped',
                'last_move_date': fields.Datetime.now(),
            })

            report.status = 'scrapped'
            report.message_post(body="✅ Damage report approved by Admin. Asset has been scrapped.")

    def action_admin_reject(self):
        """Admin rejects the damage report"""
        for report in self:
            if report.status not in ['submitted', 'line_manager_approved']:
                raise UserError('Only submitted or line manager approved reports can be rejected!')

            if not report.rejection_reason:
                raise UserError('Please provide a rejection reason!')

            report.status = 'rejected'
            report.reviewed_date = fields.Datetime.now()
            report.reviewed_by = self.env.user
            report.message_post(body=f"❌ Damage report rejected by Admin: {report.rejection_reason}")

    def action_reset_to_draft(self):
        """Reset a rejected report to draft for re-submission"""
        for report in self:
            if report.status != 'rejected':
                raise UserError('Only rejected reports can be reset!')

            report.status = 'draft'
            report.reviewed_date = False
            report.reviewed_by = False
            report.rejection_reason = False
            report.message_post(body="🔄 Report reset to draft for re-submission.")

    # === NOTIFICATIONS ===

    def _notify_line_manager(self):
        """Notify the line manager about new damage report"""
        for report in self:
            if report.line_manager_id and report.line_manager_id.user_id:
                self.env['mail.activity'].create({
                    'activity_type_id': self.env.ref('mail.mail_activity_data_todo').id,
                    'user_id': report.line_manager_id.user_id.id,
                    'res_id': report.id,
                    'res_model_id': self.env['ir.model']._get('una.asset.damage.report').id,
                    'summary': f"⚠️ Damage Report from {report.employee_name}",
                    'note': f"""
                        Asset: {report.asset_name}
                        Tag: {report.asset_tag}
                        Serial: {report.serial_number}
                        Reported By: {report.employee_name}
                        Severity: {report.damage_severity}
                        Description: {report.damage_description}
                        Reported Date: {report.reported_date}

                        Please review and approve or reject this damage report.
                    """,
                })

    def _notify_admins(self):
        """Notify admin users about new damage report"""
        for report in self:
            # Get users with admin assistant or admin manager group
            admin_users = self.env['res.users'].search([
                '|',
                ('has_group', '=', 'una_inventory_management.group_una_admin_assistant'),
                ('has_group', '=', 'una_inventory_management.group_una_admin_manager'),
            ])

            for admin in admin_users:
                self.env['mail.activity'].create({
                    'activity_type_id': self.env.ref('mail.mail_activity_data_todo').id,
                    'user_id': admin.id,
                    'res_id': report.id,
                    'res_model_id': self.env['ir.model']._get('una.asset.damage.report').id,
                    'summary': f"⚠️ Damage Report: {report.asset_name}",
                    'note': f"""
                        Asset: {report.asset_name}
                        Tag: {report.asset_tag}
                        Serial: {report.serial_number}
                        Reported By: {report.employee_name}
                        Line Manager: {report.line_manager_name or 'N/A'}
                        Severity: {report.damage_severity}
                        Source: {dict(report._fields['source'].selection).get(report.source, report.source)}
                        Description: {report.damage_description}
                        Reported Date: {report.reported_date}
                    """,
                })

            # Also post a message on the asset
            report.asset_id.message_post(
                body=f"⚠️ Damage report submitted by {report.employee_name} (Severity: {report.damage_severity})"
            )

    # === OVERRIDE CREATE TO AUTO-NOTIFY ===
    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for record in records:
            # If source is portal and has line manager, notify them
            if record.source == 'portal' and record.line_manager_id:
                record._notify_line_manager()
            else:
                record._notify_admins()
        return records