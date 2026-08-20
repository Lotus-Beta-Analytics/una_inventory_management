from odoo import models, fields, api, _
from odoo.exceptions import UserError
from datetime import datetime
import io
import xlsxwriter


class UnaReportLocationStock(models.TransientModel):
    """Location-wise Stock Report"""
    _name = 'una.report.location_stock'
    _description = 'UNA Location-wise Stock Report'
    _inherit = ['una.report.base']

    # ================================================================
    # FILTER FIELDS
    # ================================================================
    product_type = fields.Selection([
        ('all', 'All'),
        ('asset', 'Assets Only'),
        ('consumable', 'Consumables Only')
    ], string='Product Type', default='all')

    # ================================================================
    # REPORT DATA
    # ================================================================
    line_ids = fields.One2many(
        'una.report.location_stock.line',
        'report_id',
        string='Location Stock Lines',
        readonly=True
    )
    total_quantity = fields.Float(string='Total Quantity', compute='_compute_totals')
    total_value = fields.Monetary(string='Total Value', compute='_compute_totals')
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id')
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)

    # ================================================================
    # COMPUTES
    # ================================================================
    @api.depends('line_ids', 'line_ids.quantity', 'line_ids.value')
    def _compute_totals(self):
        for rec in self:
            rec.total_quantity = sum(rec.line_ids.mapped('quantity'))
            rec.total_value = sum(rec.line_ids.mapped('value'))

    # ================================================================
    # ACTIONS
    # ================================================================
    def action_generate_report(self):
        """Generate the location stock report"""
        self.line_ids.unlink()
        domain = []
        if self.location_id:
            domain.append(('location_id', '=', self.location_id.id))

        # Get all locations
        locations = self.env['una.location'].search([('active', '=', True)])

        for loc in locations:
            # Count consumables at this location
            consumable_inv = self.env['una.inventory'].search([
                ('location_id', '=', loc.id),
                ('product_id.product_type', '=', 'consumable')
            ])
            consumable_qty = sum(consumable_inv.mapped('quantity_on_hand'))
            consumable_value = 0
            for inv in consumable_inv:
                consumable_value += inv.quantity_on_hand * (inv.product_id.cost_price or 0)

            # Count assets at this location
            assets = self.env['una.asset'].search([
                ('current_location', '=', loc.id),
                ('status', 'in', ['available', 'assigned'])
            ])
            asset_count = len(assets)
            asset_value = sum(assets.mapped('cost_price'))

            # Get serial numbers for assets at this location
            asset_serials = ', '.join(assets.mapped('serial_number'))

            if consumable_qty > 0 or asset_count > 0:
                self.env['una.report.location_stock.line'].create({
                    'report_id': self.id,
                    'location_id': loc.id,
                    'location_name': loc.name,
                    'consumable_quantity': consumable_qty,
                    'consumable_value': consumable_value,
                    'asset_count': asset_count,
                    'asset_value': asset_value,
                    'asset_serials': asset_serials,
                    'quantity': consumable_qty + asset_count,
                    'value': consumable_value + asset_value,
                })

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'una.report.location_stock',
            'view_mode': 'form',
            'target': 'current',
            'res_id': self.id,
        }

    def action_export_excel(self):
        """Export report to Excel"""
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output)
        sheet = workbook.add_worksheet('Location Stock')
        bold = workbook.add_format({'bold': True})
        currency_format = workbook.add_format({'num_format': '$#,##0.00'})

        headers = ['#', 'Location', 'Consumable Qty', 'Consumable Value', 'Asset Count', 'Asset Value', 'Total Quantity', 'Total Value', 'Asset Serials']
        for col, header in enumerate(headers):
            sheet.write(0, col, header, bold)

        row = 1
        for idx, line in enumerate(self.line_ids, 1):
            sheet.write(row, 0, idx)
            sheet.write(row, 1, line.location_name)
            sheet.write(row, 2, line.consumable_quantity)
            sheet.write(row, 3, line.consumable_value, currency_format)
            sheet.write(row, 4, line.asset_count)
            sheet.write(row, 5, line.asset_value, currency_format)
            sheet.write(row, 6, line.quantity)
            sheet.write(row, 7, line.value, currency_format)
            sheet.write(row, 8, line.asset_serials or '')
            row += 1

        workbook.close()
        output.seek(0)

        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/una.report.location_stock/{self.id}/location_stock.xlsx?download=true',
            'target': 'new',
        }

    def action_export_pdf(self):
        """Export report to PDF"""
        return self.env.ref('una_inventory_management.action_report_una_location_stock').report_action(self)


class UnaReportLocationStockLine(models.TransientModel):
    """Location-wise Stock Report Line"""
    _name = 'una.report.location_stock.line'
    _description = 'UNA Location Stock Report Line'

    report_id = fields.Many2one('una.report.location_stock', string='Report', required=True)
    location_id = fields.Many2one('una.location', string='Location')
    location_name = fields.Char(string='Location Name')
    consumable_quantity = fields.Float(string='Consumable Qty', default=0.0)
    consumable_value = fields.Monetary(string='Consumable Value')
    asset_count = fields.Integer(string='Asset Count', default=0)
    asset_value = fields.Monetary(string='Asset Value')
    asset_serials = fields.Text(string='Asset Serials')
    quantity = fields.Float(string='Total Quantity', default=0.0)
    value = fields.Monetary(string='Total Value')
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)