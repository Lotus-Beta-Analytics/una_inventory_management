from odoo import models, fields, api, _
from odoo.exceptions import UserError
from datetime import datetime, timedelta
import io
import xlsxwriter


class UnaReportInventoryValuation(models.TransientModel):
    """Inventory Valuation Report"""
    _name = 'una.report.inventory_valuation'
    _description = 'UNA Inventory Valuation Report'
    _inherit = ['una.report.base']

    # ================================================================
    # FILTER FIELDS
    # ================================================================
    product_id = fields.Many2one('una.product', string='Product')
    valuation_type = fields.Selection([
        ('all', 'All'),
        ('asset', 'Assets Only'),
        ('consumable', 'Consumables Only')
    ], string='Valuation Type', default='all')

    # ================================================================
    # REPORT DATA
    # ================================================================
    line_ids = fields.One2many(
        'una.report.inventory_valuation.line',
        'report_id',
        string='Valuation Lines',
        readonly=True
    )
    total_quantity = fields.Float(string='Total Quantity', compute='_compute_totals')
    total_value = fields.Monetary(string='Total Value', compute='_compute_totals')
    total_asset_value = fields.Monetary(string='Total Asset Value', compute='_compute_totals')
    total_consumable_value = fields.Monetary(string='Total Consumable Value', compute='_compute_totals')
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
            rec.total_asset_value = sum(rec.line_ids.filtered(lambda l: l.product_type == 'asset').mapped('value'))
            rec.total_consumable_value = sum(rec.line_ids.filtered(lambda l: l.product_type == 'consumable').mapped('value'))

    # ================================================================
    # ACTIONS
    # ================================================================
    def action_generate_report(self):
        """Generate the valuation report"""
        self.line_ids.unlink()
        domain = []
        if self.product_id:
            domain.append(('product_id', '=', self.product_id.id))
        if self.location_id:
            domain.append(('location_id', '=', self.location_id.id))
        if self.valuation_type == 'asset':
            domain.append(('product_type', '=', 'asset'))
        elif self.valuation_type == 'consumable':
            domain.append(('product_type', '=', 'consumable'))

        # Get inventory lines
        inventory_lines = self.env['una.inventory'].search(domain)

        for inv in inventory_lines:
            product = inv.product_id
            if product.product_type == 'asset':
                # Count assets at this location
                assets = self.env['una.asset'].search([
                    ('product_id', '=', product.id),
                    ('current_location', '=', inv.location_id.id),
                    ('status', 'in', ['available', 'assigned'])
                ])
                quantity = len(assets)
                cost = product.cost_price or 0
                value = quantity * cost
                # Get serial numbers
                serials = ', '.join(assets.mapped('serial_number'))
            else:
                quantity = inv.quantity_on_hand
                cost = product.cost_price or 0
                value = quantity * cost
                serials = ''

            if quantity > 0:
                self.env['una.report.inventory_valuation.line'].create({
                    'report_id': self.id,
                    'product_id': product.id,
                    'product_name': product.name,
                    'product_code': product.code,
                    'product_type': product.product_type,
                    'location_id': inv.location_id.id,
                    'location_name': inv.location_id.name,
                    'quantity': quantity,
                    'unit_cost': cost,
                    'value': value,
                    'serial_numbers': serials,
                })

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'una.report.inventory_valuation',
            'view_mode': 'form',
            'target': 'current',
            'res_id': self.id,
        }

    def action_export_excel(self):
        """Export report to Excel"""
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output)
        sheet = workbook.add_worksheet('Inventory Valuation')
        bold = workbook.add_format({'bold': True})
        currency_format = workbook.add_format({'num_format': '$#,##0.00'})

        # Headers
        headers = ['#', 'Product Code', 'Product Name', 'Type', 'Location', 'Quantity', 'Unit Cost', 'Total Value', 'Serial Numbers']
        for col, header in enumerate(headers):
            sheet.write(0, col, header, bold)

        # Data
        row = 1
        for idx, line in enumerate(self.line_ids, 1):
            sheet.write(row, 0, idx)
            sheet.write(row, 1, line.product_code or '')
            sheet.write(row, 2, line.product_name)
            sheet.write(row, 3, line.product_type.capitalize())
            sheet.write(row, 4, line.location_name)
            sheet.write(row, 5, line.quantity)
            sheet.write(row, 6, line.unit_cost, currency_format)
            sheet.write(row, 7, line.value, currency_format)
            sheet.write(row, 8, line.serial_numbers or '')
            row += 1

        # Totals row
        sheet.write(row, 0, '', bold)
        sheet.write(row, 5, 'TOTAL', bold)
        sheet.write(row, 7, self.total_value, currency_format)

        workbook.close()
        output.seek(0)

        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/una.report.inventory_valuation/{self.id}/inventory_valuation.xlsx?download=true',
            'target': 'new',
        }

    def action_export_pdf(self):
        """Export report to PDF"""
        return self.env.ref('una_inventory_management.action_report_una_inventory_valuation').report_action(self)


class UnaReportInventoryValuationLine(models.TransientModel):
    """Inventory Valuation Report Line"""
    _name = 'una.report.inventory_valuation.line'
    _description = 'UNA Inventory Valuation Line'

    report_id = fields.Many2one('una.report.inventory_valuation', string='Report', required=True)
    product_id = fields.Many2one('una.product', string='Product')
    product_name = fields.Char(string='Product Name')
    product_code = fields.Char(string='Product Code')
    product_type = fields.Selection([
        ('asset', 'Asset'),
        ('consumable', 'Consumable')
    ], string='Type')
    location_id = fields.Many2one('una.location', string='Location')
    location_name = fields.Char(string='Location Name')
    quantity = fields.Float(string='Quantity', default=0.0)
    unit_cost = fields.Monetary(string='Unit Cost')
    value = fields.Monetary(string='Total Value')
    serial_numbers = fields.Text(string='Serial Numbers')
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)