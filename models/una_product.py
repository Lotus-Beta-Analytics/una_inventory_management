from odoo import models, fields, api
from odoo.exceptions import ValidationError


class UnaProduct(models.Model):
    _name = 'una.product'
    _description = 'UNA Product'
    _rec_name = 'name'
    _order = 'name'

    # === BASIC FIELDS ===
    name = fields.Char(string='Product Name', required=True)
    code = fields.Char(string='Product Code', required=True, unique=True)
    description = fields.Text(string='Description')

    # === TYPE ===
    product_type = fields.Selection([
        ('asset', 'Asset'),
        ('consumable', 'Consumable')
    ], string='Type', required=True, default='consumable')

    odoo_product_id = fields.Many2one(
        'product.product',
        string='Odoo Product',
        readonly=True,
        help="Linked Odoo product"
    )

    # === UOM ===
    uom_id = fields.Many2one(
        'uom.uom',
        string='Unit of Measure',
        required=True,
        default=lambda self: self.env.ref('uom.product_uom_unit', raise_if_not_found=False)
    )

    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id,
        required=True
    )

    cost_price = fields.Monetary(
        string='Cost Price',
        currency_field='currency_id',
        default=1.00,
        help="Current cost price of this product"
    )

    is_serial_tracked = fields.Boolean(
        string='Track Serial Numbers',
        default=False,
        help="If checked, each unit gets a unique serial number"
    )

    is_bundle = fields.Boolean(
        default=False,
        help="Enable bundle UOM for this product"
    )

    bundle_uom_id = fields.Many2one(
        'uom.uom',
        string='Bundle UOM',
        help="Unit of Measure for bundles (e.g., Box, Carton, Pack)"
    )

    bundle_quantity = fields.Float(
        string='Units per Bundle',
        default=1.0,
        help="Number of base units in one bundle (e.g., 10 for 1 Box = 10 Units)"
    )

    # === ★ DISPLAY FIELD ===
    bundle_display_name = fields.Char(
        string='Bundle Info',
        compute='_compute_bundle_display_name',
        store=False,
        help="Displays: 1 Box = 10 Each"
    )


    @api.depends('is_bundle', 'bundle_uom_id', 'bundle_quantity', 'uom_id')
    def _compute_bundle_display_name(self):
        for rec in self:
            if not rec.is_bundle:
                rec.bundle_display_name = ""
            elif not rec.bundle_uom_id or not rec.uom_id:
                rec.bundle_display_name = "Please configure bundle"
            elif rec.bundle_uom_id == rec.uom_id:
                rec.bundle_display_name = "⚠️ Select a different Bundle UOM"
            else:
                rec.bundle_display_name = f"1 {rec.bundle_uom_id.name} = {rec.bundle_quantity:.0f} {rec.uom_id.name}"

    # === ★ BUNDLE CONVERSION HELPER METHODS ===
    def convert_bundle_to_unit(self, bundle_qty):
        """Convert bundle quantity to base units"""
        self.ensure_one()
        if not self.is_bundle or self.bundle_quantity <= 0:
            return bundle_qty
        return bundle_qty * self.bundle_quantity

    def convert_unit_to_bundle(self, unit_qty):
        """Convert base units to bundle quantity"""
        self.ensure_one()
        if not self.is_bundle or self.bundle_quantity <= 0:
            return unit_qty
        return unit_qty / self.bundle_quantity

    def get_bundle_display(self, unit_qty):
        """Get display string showing both units and bundles"""
        self.ensure_one()
        if not self.is_bundle or self.bundle_quantity <= 0:
            return f"{unit_qty:.0f} {self.uom_id.name}"

        bundle_qty = self.convert_unit_to_bundle(unit_qty)
        return f"{unit_qty:.0f} {self.uom_id.name} ({bundle_qty:.1f} {self.bundle_uom_id.name})"

    # === ONCHANGE TO SET DOMAIN ON BUNDLE UOM ===
    @api.onchange('uom_id')
    def _onchange_uom_id(self):
        """Update bundle UOM domain when base UOM changes"""
        if self.uom_id:
            return {
                'domain': {
                    'bundle_uom_id': [('category_id', '=', self.uom_id.category_id.id)]
                }
            }
        return {
            'domain': {
                'bundle_uom_id': []
            }
        }

    # === CONSTRAINTS ===
    @api.constrains('bundle_uom_id', 'uom_id')
    def _check_bundle_uom_category(self):
        """Ensure bundle UOM is in the same category as base UOM"""
        for rec in self:
            if rec.is_bundle and rec.bundle_uom_id:
                if rec.bundle_uom_id.category_id != rec.uom_id.category_id:
                    raise ValidationError(
                        f"Bundle UOM '{rec.bundle_uom_id.name}' must be in the same category "
                        f"as base UOM '{rec.uom_id.name}'.\n"
                        f"Base UOM Category: {rec.uom_id.category_id.name}\n"
                        f"Bundle UOM Category: {rec.bundle_uom_id.category_id.name}"
                    )

    @api.constrains('bundle_quantity')
    def _check_bundle_quantity(self):
        """Ensure bundle quantity is positive"""
        for rec in self:
            if rec.is_bundle and rec.bundle_quantity <= 0:
                raise ValidationError("Bundle quantity must be greater than zero!")

    @api.constrains('cost_price')
    def _check_cost_price(self):
        for rec in self:
            if rec.cost_price <= 0:
                raise ValidationError('Cost price must be greater than zero!')

    @api.constrains('min_stock', 'max_stock', 'reorder_point')
    def _check_stock_levels(self):
        for rec in self:
            if rec.min_stock > rec.max_stock:
                raise ValidationError('Minimum stock cannot exceed maximum stock!')
            if rec.reorder_point < rec.min_stock:
                raise ValidationError('Reorder point cannot go below the minimum stock!')

    # === STOCK LEVELS ===
    min_stock = fields.Float(string='Minimum Stock', default=0.0)
    max_stock = fields.Float(string='Maximum Stock', default=0.0)
    reorder_point = fields.Float(string='Reorder Point', default=0.0)

    # === STATUS ===
    active = fields.Boolean(string='Active', default=True)

    # === SQL CONSTRAINTS ===
    _sql_constraints = [
        ('unique_code', 'unique(code)', 'Product code must be unique!'),
        ('cost_positive', 'CHECK(cost_price > 0)', 'Cost price must be greater than zero!')
    ]