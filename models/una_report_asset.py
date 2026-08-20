from odoo import models, fields, api, _
from odoo.exceptions import UserError
from datetime import datetime
import io
import xlsxwriter


class UnaReportAsset(models.TransientModel):
    """Asset Report"""
    _name = 'una.report.asset'
    _description = 'UNA Asset Report'
    _inherit = ['una.report.base']

    # ================================================================
    # FILTER FIELDS
    # ================================================================
    product_id = fields.Many2one('una.product', string='Product')
    status = fields.Selection([
        ('available', 'Available'),
        ('assigned', 'Assigned'),
        ('scrapped', 'Scrapped'),
        ('missing', 'Missing')
    ], string='Status')
    assigned_to = fields.Many2one('hr.employee', string='Assigned To')

    # ================================================================
    # REPORT DATA
    # ================================================================
    line_ids = fields.One2many(
        'una.report.asset.line',
        'report_id',
        string='Asset Lines',
        readonly=True
    )
    total_assets = fields.Integer(string='Total Assets', compute='_compute_totals')
    total_value = fields.Monetary(string='Total Value', compute='_compute_totals')
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id')
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)

    # ================================================================
    # COMPUTES
    # ================================================================
    @api.depends('line_ids', 'line_ids.cost_price')
    def _compute_totals(self):
        for rec in self:
            rec.total_assets = len(rec.line_ids)
            rec.total_value = sum(rec.line_ids.mapped('cost_price'))

    # ================================================================
    # ACTIONS
    # ================================================================
    def action_generate_report(self):
        """Generate the asset report"""
        self.line_ids.unlink()
        domain = []
        if self.product_id:
            domain.append(('product_id', '=', self.product_id.id))
        if self.location_id:
            domain.append(('current_location', '=', self.location_id.id))
        if self.status:
            domain.append(('status', '=', self.status))
        if self.assigned_to:
            domain.append(('assigned_to', '=', self.assigned_to.id))

        assets = self.env['una.asset'].search(domain)

        for asset in assets:
            self.env['una.report.asset.line'].create({
                'report_id': self.id,
                'asset_id': asset.id,
                'asset_tag': asset.asset_tag,
                'serial_number': asset.serial_number,
                'name': asset.name,
                'product_id': asset.product_id.id,
                'product_name': asset.product_id.name,
                'status': asset.status,
                'current_location_id': asset.current_location.id if asset.current_location else False,
                'current_location': asset.current_location.name if asset.current_location else 'N/A',
                'source_location': asset.source_location.name if asset.source_location else 'N/A',
                'cost_price': asset.cost_price,
                'purchase_date': asset.purchase_date,
                'assigned_to': asset.assigned_to.name if asset.assigned_to else 'N/A',
                'assigned_date': asset.assigned_date,
                'last_move_date': asset.last_move_date,
            })

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'una.report.asset',
            'view_mode': 'form',
            'target': 'current',
            'res_id': self.id,
        }

    def action_export_excel(self):
        """Export report to Excel"""
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output)
        sheet = workbook.add_worksheet('Assets')
        bold = workbook.add_format({'bold': True})
        currency_format = workbook.add_format({'num_format': '$#,##0.00'})

        headers = ['#', 'Asset Tag', 'Serial Number', 'Name', 'Product', 'Status', 'Current Location', 'Source Location', 'Cost Price', 'Purchase Date', 'Assigned To', 'Assigned Date', 'Last Move Date']
        for col, header in enumerate(headers):
            sheet.write(0, col, header, bold)

        row = 1
        for idx, line in enumerate(self.line_ids, 1):
            sheet.write(row, 0, idx)
            sheet.write(row, 1, line.asset_tag or '')
            sheet.write(row, 2, line.serial_number or '')
            sheet.write(row, 3, line.name or '')
            sheet.write(row, 4, line.product_name or '')
            sheet.write(row, 5, line.status.capitalize() if line.status else '')
            sheet.write(row, 6, line.current_location or '')
            sheet.write(row, 7, line.source_location or '')
            sheet.write(row, 8, line.cost_price, currency_format)
            sheet.write(row, 9, line.purchase_date.strftime('%Y-%m-%d') if line.purchase_date else '')
            sheet.write(row, 10, line.assigned_to or '')
            sheet.write(row, 11, line.assigned_date.strftime('%Y-%m-%d') if line.assigned_date else '')
            sheet.write(row, 12, line.last_move_date.strftime('%Y-%m-%d %H:%M') if line.last_move_date else '')
            row += 1

        workbook.close()
        output.seek(0)

        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/una.report.asset/{self.id}/asset_report.xlsx?download=true',
            'target': 'new',
        }

    def action_export_pdf(self):
        """Export report to PDF"""
        return self.env.ref('una_inventory_management.action_report_una_asset').report_action(self)


class UnaReportAssetLine(models.TransientModel):
    """Asset Report Line"""
    _name = 'una.report.asset.line'
    _description = 'UNA Asset Report Line'

    report_id = fields.Many2one('una.report.asset', string='Report', required=True)
    asset_id = fields.Many2one('una.asset', string='Asset')
    asset_tag = fields.Char(string='Asset Tag')
    serial_number = fields.Char(string='Serial Number')
    name = fields.Char(string='Name')
    product_id = fields.Many2one('una.product', string='Product')
    product_name = fields.Char(string='Product Name')
    status = fields.Selection([
        ('available', 'Available'),
        ('assigned', 'Assigned'),
        ('scrapped', 'Scrapped'),
        ('missing', 'Missing')
    ], string='Status')
    current_location_id = fields.Many2one('una.location', string='Current Location')
    current_location = fields.Char(string='Current Location Name')
    source_location = fields.Char(string='Source Location')
    cost_price = fields.Monetary(string='Cost Price')
    purchase_date = fields.Date(string='Purchase Date')
    assigned_to = fields.Char(string='Assigned To')
    assigned_date = fields.Date(string='Assigned Date')
    last_move_date = fields.Datetime(string='Last Move Date')
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)