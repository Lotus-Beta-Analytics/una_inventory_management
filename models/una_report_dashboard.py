from odoo import models, fields, api, _
from odoo.exceptions import UserError
from datetime import datetime, timedelta
import io
import xlsxwriter
import base64


class UnaReportDashboard(models.TransientModel):
    _name = 'una.report.dashboard'
    _description = 'UNA Dashboard Report'
    _inherit = ['una.report.base']

    # ================================================================
    # DASHBOARD DATA STRUCTURE
    # ================================================================
    total_inventory_value = fields.Monetary(string='Total Inventory Value', readonly=True)
    total_assets = fields.Integer(string='Total Assets', readonly=True)
    pending_requisitions = fields.Integer(string='Pending Requisitions', readonly=True)
    total_stock_counts = fields.Integer(string='Total Stock Counts', readonly=True)
    stock_count_discrepancies = fields.Integer(string='Stock Count Discrepancies', readonly=True)

    inventory_by_location = fields.Text(string='Inventory by Location', readonly=True)
    inventory_by_type = fields.Text(string='Inventory by Type', readonly=True)
    requisition_by_state = fields.Text(string='Requisition by State', readonly=True)
    stock_movements_by_type = fields.Text(string='Stock Movements by Type', readonly=True)

    # Changed from fields.Text to fields.Html for professional frontend layout
    recent_movements = fields.Html(string='Recent Movements', readonly=True)
    low_stock_alerts = fields.Html(string='Low Stock Alerts', readonly=True)

    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id.id, readonly=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)

    # ================================================================
    # COMPUTE DASHBOARD DATA
    # ================================================================
    @api.depends()
    def _compute_dashboard_data(self):
        """Compute all dashboard data"""
        for record in self:
            data = record._get_dashboard_data()
            record.update(data)

    @api.model
    def default_get(self, fields_list):
        result = super().default_get(fields_list)

        result['company_id'] = self.env.company.id
        result['currency_id'] = self.env.company.currency_id.id

        temp = self.new(result)
        result.update(temp._get_dashboard_data())

        return result

    def _get_dashboard_data(self):
        """Get all dashboard data with clean formatting"""
        result = {}

        # ============================================================
        # 1. Total Inventory Value
        # ============================================================
        inventory_lines = self.env['una.inventory'].search([])
        total_value = 0
        for inv in inventory_lines:
            if inv.product_id.product_type == 'asset':
                assets = self.env['una.asset'].search([
                    ('product_id', '=', inv.product_id.id),
                    ('current_location', '=', inv.location_id.id),
                    ('status', 'in', ['available', 'assigned'])
                ])
                total_value += sum(assets.mapped('cost_price'))
            else:
                total_value += inv.quantity_on_hand * (inv.product_id.cost_price or 0)
        result['total_inventory_value'] = total_value

        # ============================================================
        # 2. Total Assets
        # ============================================================
        result['total_assets'] = self.env['una.asset'].search_count([
            ('status', 'in', ['available', 'assigned'])
        ])

        # ============================================================
        # 3. Pending Requisitions
        # ============================================================
        result['pending_requisitions'] = self.env['una.requisition'].search_count([
            ('state', 'in', ['submitted', 'line_manager_approved', 'admin_assistant_approved',
                             'admin_manager_approved', 'director_approved'])
        ])

        # ============================================================
        # 4. Stock Counts
        # ============================================================
        result['total_stock_counts'] = self.env['una.stock.count'].search_count([])
        result['stock_count_discrepancies'] = self.env['una.stock.count'].search_count([
            ('has_discrepancy', '=', True)
        ])

        # ============================================================
        # 5. Inventory by Location
        # ============================================================
        location_data = []
        locations = self.env['una.location'].search([('active', '=', True)])
        for loc in locations:
            inv_lines = self.env['una.inventory'].search([('location_id', '=', loc.id)])
            loc_value = 0
            for inv in inv_lines:
                if inv.product_id.product_type == 'asset':
                    assets = self.env['una.asset'].search([
                        ('product_id', '=', inv.product_id.id),
                        ('current_location', '=', loc.id),
                        ('status', 'in', ['available', 'assigned'])
                    ])
                    loc_value += sum(assets.mapped('cost_price'))
                else:
                    loc_value += inv.quantity_on_hand * (inv.product_id.cost_price or 0)
            if loc_value > 0:
                location_data.append({
                    'name': loc.name,
                    'value': loc_value
                })

        location_text = ""
        if location_data:
            for item in sorted(location_data, key=lambda x: x['value'], reverse=True):
                location_text += f"🏢 {item['name']}: {self._format_currency(item['value'])}\n"
        else:
            location_text = "No inventory data available"
        result['inventory_by_location'] = location_text

        # ============================================================
        # 6. Inventory by Type
        # ============================================================
        asset_value = 0
        consumable_value = 0
        all_inventory = self.env['una.inventory'].search([])
        for inv in all_inventory:
            if inv.product_id.product_type == 'asset':
                assets = self.env['una.asset'].search([
                    ('product_id', '=', inv.product_id.id),
                    ('current_location', '=', inv.location_id.id),
                    ('status', 'in', ['available', 'assigned'])
                ])
                asset_value += sum(assets.mapped('cost_price'))
            else:
                consumable_value += inv.quantity_on_hand * (inv.product_id.cost_price or 0)

        type_text = ""
        type_text += f"📦 Assets: {self._format_currency(asset_value)}\n"
        type_text += f"📦 Consumables: {self._format_currency(consumable_value)}"
        result['inventory_by_type'] = type_text

        # ============================================================
        # 7. Requisition by State
        # ============================================================
        state_data = []
        state_counts = {}
        states = ['draft', 'submitted', 'line_manager_approved', 'admin_assistant_approved',
                  'admin_manager_approved', 'director_approved', 'audit_approved', 'rejected']
        for state in states:
            count = self.env['una.requisition'].search_count([('state', '=', state)])
            if count > 0:
                state_counts[state] = count
        for state, count in state_counts.items():
            state_data.append({
                'name': dict(self.env['una.requisition']._fields['state'].selection).get(state, state),
                'value': count
            })

        state_text = ""
        if state_data:
            for item in state_data:
                state_text += f" {item['name']}: {item['value']}\n"
        else:
            state_text = "No requisitions found"
        result['requisition_by_state'] = state_text

        # ============================================================
        # 8. Stock Movements by Type
        # ============================================================
        move_types = ['receipt', 'issue', 'transfer', 'scrap', 'adjustment']
        move_data = []
        move_type_names = {
            'receipt': 'Receipt', 'issue': 'Issue', 'transfer': 'Transfer', 'scrap': 'Scrap', 'adjustment': 'Adjustment'
        }
        move_type_icons = {
            'receipt': '📥', 'issue': '📤', 'transfer': '🔄', 'scrap': '🗑️', 'adjustment': '📝'
        }
        for move_type in move_types:
            count = self.env['una.stock.move'].search_count([
                ('move_type', '=', move_type),
                ('state', '=', 'confirmed')
            ])
            if count > 0:
                move_data.append({
                    'name': move_type_names.get(move_type, move_type),
                    'icon': move_type_icons.get(move_type, '📌'),
                    'value': count
                })

        move_text = ""
        if move_data:
            for item in move_data:
                move_text += f"{item['icon']} {item['name']}: {item['value']}\n"
        else:
            move_text = "No stock movements found"
        result['stock_movements_by_type'] = move_text

        # CSS Styling Configurations for Tables
        table_style = "width: 100%; border-collapse: separate; border-spacing: 0; font-size: 13px; color: #2d3436;"
        th_style = "background-color: #f8f9fa; color: #495057; font-weight: 600; padding: 10px 12px; border-bottom: 2px solid #dee2e6; text-align: left;"
        td_style = "padding: 10px 12px; border-bottom: 1px solid #dee2e6; vertical-align: middle;"

        # ============================================================
        # 9. Recent Movements (HTML Layout Upgrade)
        # ============================================================
        recent = self.env['una.stock.move'].search([
            ('state', '=', 'confirmed')
        ], order='create_date desc', limit=10)

        move_type_icons_small = {
            'receipt': '📥', 'issue': '📤', 'transfer': '🔄', 'scrap': '🗑️', 'adjustment': '📝'
        }
        move_type_names_small = {
            'receipt': 'Receipt', 'issue': 'Issue', 'transfer': 'Transfer', 'scrap': 'Scrap', 'adjustment': 'Adjustment'
        }

        if recent:
            html = f'<table style="{table_style}">'
            html += f'<thead><tr><th style="{th_style}">Ref</th><th style="{th_style}">Type</th><th style="{th_style}">Product</th><th style="{th_style} text-align: right;">Qty</th><th style="{th_style}">Route</th></tr></thead><tbody>'
            for move in recent:
                icon = move_type_icons_small.get(move.move_type, '📌')
                move_type = move_type_names_small.get(move.move_type, move.move_type)
                from_loc = move.source_location.name if move.source_location else '—'
                to_loc = move.destination_location.name if move.destination_location else '—'

                html += f'<tr>'
                html += f'<td style="{td_style} font-weight: 600; color: #283593;">{move.reference or "—"}</td>'
                html += f'<td style="{td_style}">{icon} {move_type}</td>'
                html += f'<td style="{td_style} white-space: nowrap; max-width: 160px; overflow: hidden; text-overflow: ellipsis;">{move.product_id.name}</td>'
                html += f'<td style="{td_style} text-align: right; font-weight: 600;">{move.quantity}</td>'
                html += f'<td style="{td_style} font-size: 12px; color: #6c757d;">{from_loc} → {to_loc}</td>'
                html += f'</tr>'
            html += '</tbody></table>'
            result['recent_movements'] = html
        else:
            result[
                'recent_movements'] = '<div style="text-align: center; padding: 20px; color: #adb5bd;">No recent movements</div>'

        # ============================================================
        # 10. Low Stock Alerts (HTML Layout Upgrade)
        # ============================================================
        low_stock = []
        inventory = self.env['una.inventory'].search([
            ('quantity_on_hand', '>', 0)
        ])
        for inv in inventory:
            if inv.product_id.min_stock > 0 and inv.quantity_on_hand <= inv.product_id.min_stock:
                badge_color = '#d32f2f' if inv.quantity_on_hand <= inv.product_id.min_stock / 2 else '#f57c00'
                bg_color = '#ffebee' if inv.quantity_on_hand <= inv.product_id.min_stock / 2 else '#fff3e0'
                status_label = 'Critical' if inv.quantity_on_hand <= inv.product_id.min_stock / 2 else 'Low Stock'

                low_stock.append({
                    'product': inv.product_id.name,
                    'location': inv.location_id.name,
                    'on_hand': inv.quantity_on_hand,
                    'min_stock': inv.product_id.min_stock,
                    'badge': f'<span style="background-color: {bg_color}; color: {badge_color}; padding: 3px 8px; border-radius: 4px; font-weight: 600; font-size: 11px;">{status_label}</span>'
                })

        if low_stock:
            html = f'<table style="{table_style}">'
            html += f'<thead><tr><th style="{th_style}">Alert</th><th style="{th_style}">Product</th><th style="{th_style}">Location</th><th style="{th_style} text-align: right;">On Hand</th><th style="{th_style} text-align: right;">Min</th></tr></thead><tbody>'
            for item in sorted(low_stock, key=lambda x: x['on_hand']):
                html += f'<tr>'
                html += f'<td style="{td_style}">{item["badge"]}</td>'
                html += f'<td style="{td_style} font-weight: 500;">{item["product"]}</td>'
                html += f'<td style="{td_style} color: #495057;">{item["location"]}</td>'
                html += f'<td style="{td_style} text-align: right; color: #d32f2f; font-weight: 600;">{item["on_hand"]}</td>'
                html += f'<td style="{td_style} text-align: right; color: #6c757d;">{item["min_stock"]}</td>'
                html += f'</tr>'
            html += '</tbody></table>'
            result['low_stock_alerts'] = html
        else:
            result[
                'low_stock_alerts'] = '<div style="text-align: center; padding: 20px; color: #2e7d32; font-weight: 500;">✅ All stock levels are healthy</div>'

        return result

    # ================================================================
    # ACTIONS
    # ================================================================
    def action_refresh_dashboard(self):
        """Refresh dashboard data"""
        self._compute_dashboard_data()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'una.report.dashboard',
            'view_mode': 'form',
            'target': 'current',
            'res_id': self.id,
        }

    # def action_export_pdf(self):
    #     """Export dashboard as PDF"""
    #     # ★ Check if the report exists first
    #     report = self.env.ref('una_inventory_management.action_report_una_dashboard', raise_if_not_found=False)
    #     if report:
    #         return report.report_action(self)
    #     else:
    #         # ★ Fallback: Use simple HTML to PDF
    #         return self._export_pdf_fallback()
    #
    # def _export_pdf_fallback(self):
    #     """Fallback PDF export using HTML"""
    #     data = self._get_dashboard_data()
    #     html = f"""
    #     <html>
    #     <head>
    #         <style>
    #             body {{ font-family: Arial, sans-serif; padding: 20px; }}
    #             h1 {{ color: #1a237e; }}
    #             .card {{ background: #f5f5f5; padding: 10px; margin: 10px 0; border-radius: 4px; }}
    #             table {{ width: 100%; border-collapse: collapse; }}
    #             th {{ background: #e8eaf6; padding: 8px; text-align: left; border: 1px solid #ddd; }}
    #             td {{ padding: 8px; border: 1px solid #ddd; }}
    #         </style>
    #     </head>
    #     <body>
    #         <h1>📊 UNA Inventory Dashboard</h1>
    #         <p>Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>
    #         <hr/>
    #         <div class="card">
    #             <h3>Total Inventory Value: ${data.get('total_inventory_value', 0):,.2f}</h3>
    #             <h3>Total Assets: {data.get('total_assets', 0)}</h3>
    #             <h3>Pending Requisitions: {data.get('pending_requisitions', 0)}</h3>
    #             <h3>Stock Count Discrepancies: {data.get('stock_count_discrepancies', 0)}</h3>
    #         </div>
    #         <hr/>
    #         <h3>📋 Inventory by Location</h3>
    #         <pre>{data.get('inventory_by_location', 'No data')}</pre>
    #         <hr/>
    #         <h3>🔄 Recent Movements</h3>
    #         <div>{data.get('recent_movements', 'No recent movements')}</div>
    #         <hr/>
    #         <h3>⚠️ Low Stock Alerts</h3>
    #         <div>{data.get('low_stock_alerts', 'All stock levels are healthy')}</div>
    #     </body>
    #     </html>
    #     """
    #     return {
    #         'type': 'ir.actions.act_url',
    #         'url': f'/web/print?report_type=pdf&data={html}',
    #         'target': 'new',
    #     }
    #
    # def action_export_excel(self):
    #     """Export dashboard as Excel"""
    #     data = self._get_dashboard_data()
    #     output = io.BytesIO()
    #     workbook = xlsxwriter.Workbook(output)
    #
    #     self._write_dashboard_sheet(workbook, data)
    #     self._write_inventory_sheet(workbook)
    #     self._write_movements_sheet(workbook)
    #
    #     workbook.close()
    #     output.seek(0)
    #
    #     # ★ FIXED: Create attachment and return download URL
    #     attachment = self.env['ir.attachment'].sudo().create({
    #         'name': f'Inventory_Dashboard_{fields.Datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx',
    #         'datas': base64.b64encode(output.getvalue()),
    #         'res_model': 'una.report.dashboard',
    #         'res_id': self.id,
    #         'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    #     })
    #
    #     return {
    #         'type': 'ir.actions.act_url',
    #         'url': f'/web/content/{attachment.id}?download=true&filename={attachment.name}',
    #         'target': 'self',
    #     }

    def _write_dashboard_sheet(self, workbook, data):
        """Write dashboard summary sheet"""
        sheet = workbook.add_worksheet('Dashboard')
        bold = workbook.add_format({'bold': True})
        currency_format = workbook.add_format({'num_format': '$#,##0.00'})

        sheet.write(0, 0, 'UNA Inventory Dashboard', bold)
        sheet.write(1, 0, f'Generated: {datetime.now().strftime("%Y-%m-%d %H:%M")}', bold)
        sheet.write(3, 0, 'Metric', bold)
        sheet.write(3, 1, 'Value', bold)

        row = 4
        metrics = [
            ('Total Inventory Value', data.get('total_inventory_value', 0)),
            ('Total Assets', data.get('total_assets', 0)),
            ('Pending Requisitions', data.get('pending_requisitions', 0)),
            ('Total Stock Counts', data.get('total_stock_counts', 0)),
            ('Stock Count Discrepancies', data.get('stock_count_discrepancies', 0)),
        ]
        for name, value in metrics:
            sheet.write(row, 0, name)
            if isinstance(value, (int, float)):
                sheet.write(row, 1, value)
            else:
                sheet.write(row, 1, value)
            row += 1

    def _write_inventory_sheet(self, workbook):
        """Write inventory details sheet"""
        sheet = workbook.add_worksheet('Inventory')
        bold = workbook.add_format({'bold': True})
        currency_format = workbook.add_format({'num_format': '$#,##0.00'})

        sheet.write(0, 0, 'Product', bold)
        sheet.write(0, 1, 'Location', bold)
        sheet.write(0, 2, 'On Hand', bold)
        sheet.write(0, 3, 'Total Value', bold)

        row = 1
        inventory = self.env['una.inventory'].search([])
        for inv in inventory:
            sheet.write(row, 0, inv.product_id.name)
            sheet.write(row, 1, inv.location_id.name)
            sheet.write(row, 2, inv.quantity_on_hand)
            if inv.product_id.product_type == 'asset':
                assets = self.env['una.asset'].search([
                    ('product_id', '=', inv.product_id.id),
                    ('current_location', '=', inv.location_id.id),
                    ('status', 'in', ['available', 'assigned'])
                ])
                value = sum(assets.mapped('cost_price'))
            else:
                value = inv.quantity_on_hand * (inv.product_id.cost_price or 0)
            sheet.write(row, 3, value, currency_format)
            row += 1

    def _write_movements_sheet(self, workbook):
        """Write movements sheet"""
        sheet = workbook.add_worksheet('Movements')
        bold = workbook.add_format({'bold': True})

        sheet.write(0, 0, 'Reference', bold)
        sheet.write(0, 1, 'Type', bold)
        sheet.write(0, 2, 'Product', bold)
        sheet.write(0, 3, 'Quantity', bold)
        sheet.write(0, 4, 'Date', bold)
        sheet.write(0, 5, 'From', bold)
        sheet.write(0, 6, 'To', bold)

        row = 1
        moves = self.env['una.stock.move'].search([
            ('state', '=', 'confirmed')
        ], order='create_date desc', limit=100)
        for move in moves:
            sheet.write(row, 0, move.reference)
            sheet.write(row, 1, dict(move._fields['move_type'].selection).get(move.move_type, move.move_type))
            sheet.write(row, 2, move.product_id.name)
            sheet.write(row, 3, move.quantity)
            sheet.write(row, 4, move.move_date.strftime('%Y-%m-%d %H:%M') if move.move_date else '')
            sheet.write(row, 5, move.source_location.name if move.source_location else '')
            sheet.write(row, 6, move.destination_location.name if move.destination_location else '')
            row += 1