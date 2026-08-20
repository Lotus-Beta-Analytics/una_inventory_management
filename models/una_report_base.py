from odoo import models, fields, api, _
from odoo.exceptions import UserError
from datetime import datetime, timedelta


class UnaReportBase(models.AbstractModel):
    """Base model for all UNA reports"""
    _name = 'una.report.base'
    _description = 'UNA Report Base'

    # ================================================================
    # COMMON FILTER FIELDS
    # ================================================================
    date_from = fields.Date(string='Date From', default=lambda self: fields.Date.today() - timedelta(days=30))
    date_to = fields.Date(string='Date To', default=fields.Date.today)
    location_id = fields.Many2one('una.location', string='Location')
    product_type = fields.Selection([
        ('asset', 'Asset'),
        ('consumable', 'Consumable')
    ], string='Product Type')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('cancelled', 'Cancelled'),
        ('submitted', 'Submitted'),
        ('line_manager_approved', 'Line Manager Approved'),
        ('admin_assistant_approved', 'Admin Assistant Approved'),
        ('admin_manager_approved', 'Admin Manager Approved'),
        ('director_approved', 'Director Approved'),
        ('audit_approved', 'Audit Approved'),
        ('rejected', 'Rejected'),
        ('in_progress', 'In Progress')
    ], string='State')

    # ================================================================
    # COMMON METHODS
    # ================================================================
    def _get_currency(self):
        """Get company currency"""
        return self.env.company.currency_id

    def _format_currency(self, amount):
        """Format amount as currency string using company currency"""
        currency = self._get_currency()
        if currency:
            return currency.format(amount)
        # Fallback if no currency found
        return f"{amount:,.2f}"

    def _get_date_range(self):
        """Get formatted date range string"""
        date_from = self.date_from or fields.Date.today() - timedelta(days=30)
        date_to = self.date_to or fields.Date.today()
        return f"{date_from.strftime('%Y-%m-%d')} to {date_to.strftime('%Y-%m-%d')}"

    def _apply_filters(self, domain):
        """Apply common filters to domain"""
        if self.date_from:
            domain.append(('create_date', '>=', self.date_from))
        if self.date_to:
            domain.append(('create_date', '<=', self.date_to + timedelta(days=1)))
        if self.location_id:
            domain.append(('location_id', '=', self.location_id.id))
        if self.product_type:
            domain.append(('product_type', '=', self.product_type))
        if self.state:
            domain.append(('state', '=', self.state))
        return domain

    def action_export_excel(self):
        """Export report to Excel - to be overridden by child classes"""
        raise UserError('Export Excel method must be implemented in child class')

    def action_export_pdf(self):
        """Export report to PDF - to be overridden by child classes"""
        raise UserError('Export PDF method must be implemented in child class')

    def _get_report_data(self):
        """Get report data - to be overridden by child classes"""
        return {}

    def _get_report_name(self):
        """Get report name - to be overridden by child classes"""
        return 'Report'