from odoo import models, fields, api


class UnaReport(models.AbstractModel):
    _name = 'una.report'
    _description = 'UNA Reports'

    @api.model
    def get_asset_register(self):
        """Generate asset register report"""
        assets = self.env['una.asset'].search([])

        return {
            'total': len(assets),
            'total_value': sum(assets.mapped('cost_price')),
            'by_status': {
                'available': assets.filtered(lambda a: a.status == 'available'),
                'assigned': assets.filtered(lambda a: a.status == 'assigned'),
                'scrapped': assets.filtered(lambda a: a.status == 'scrapped'),
            },
            'by_location': self._group_by_location(assets),
            'by_product': self._group_by_product(assets),
        }

    @api.model
    def _group_by_location(self, assets):
        """Group assets by location"""
        result = {}
        for asset in assets:
            loc = asset.current_location.name if asset.current_location else 'Unknown'
            if loc not in result:
                result[loc] = []
            result[loc].append({
                'name': asset.name,
                'serial': asset.serial_number,
                'tag': asset.asset_tag,
                'status': asset.status,
                'cost': asset.cost_price,
            })
        return result

    @api.model
    def _group_by_product(self, assets):
        """Group assets by product"""
        result = {}
        for asset in assets:
            product = asset.product_id.name
            if product not in result:
                result[product] = {
                    'count': 0,
                    'total_value': 0,
                    'assets': []
                }
            result[product]['count'] += 1
            result[product]['total_value'] += asset.cost_price
            result[product]['assets'].append({
                'name': asset.name,
                'serial': asset.serial_number,
                'tag': asset.asset_tag,
                'status': asset.status,
                'cost': asset.cost_price,
            })
        return result