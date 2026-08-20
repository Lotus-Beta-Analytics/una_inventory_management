from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError


class UnaInventory(models.Model):
    _name = 'una.inventory'
    _description = 'UNA Inventory'
    _rec_name = 'product_id'
    _order = 'product_id'

    # === BASIC FIELDS ===
    product_id = fields.Many2one('una.product', string='Product', required=True)
    location_id = fields.Many2one('una.location', string='Location', required=True)

    # === STOCK QUANTITIES ===
    quantity_on_hand = fields.Float(
        string='On Hand',
        default=0.0,
        digits='Product Unit of Measure'
    )

    reserved_quantity = fields.Float(
        string='Reserved',
        default=0.0,
        digits='Product Unit of Measure'
    )

    available_quantity = fields.Float(
        string='Available',
        compute='_compute_available',
        store=True,
        digits='Product Unit of Measure'
    )

    # === BUNDLE FIELDS ===
    quantity_in_bundles = fields.Float(
        string='Bundles',
        compute='_compute_bundle_display',
        store=False,
        help="Quantity expressed in bundles"
    )

    bundle_display = fields.Char(
        string='Stock Summary',
        compute='_compute_bundle_display',
        store=False,
        help="Shows: X Units (Y Bundles)"
    )

    is_bundle_product = fields.Boolean(
        string='Is Bundle Product',
        related='product_id.is_bundle',
        store=False,
        help="Whether this product uses bundle UOM"
    )

    # === VALUE ===
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id,
        required=True
    )

    total_value = fields.Monetary(
        string='Total Value',
        currency_field='currency_id',
        compute='_compute_total_value',
        store=True,
        help="Quantity × Cost Price"
    )

    # === SQL CONSTRAINTS ===
    _sql_constraints = [
        ('unique_product_location', 'unique(product_id, location_id)',
         'Product and location must be unique!')
    ]

    # === COMPUTES ===
    @api.depends('quantity_on_hand', 'reserved_quantity')
    def _compute_available(self):
        for rec in self:
            rec.available_quantity = rec.quantity_on_hand - rec.reserved_quantity

    @api.depends('quantity_on_hand', 'product_id', 'product_id.is_bundle', 'product_id.bundle_quantity', 'product_id.uom_id', 'product_id.bundle_uom_id')
    def _compute_bundle_display(self):
        for rec in self:
            if rec.product_id.is_bundle and rec.product_id.bundle_quantity > 0:
                rec.quantity_in_bundles = rec.quantity_on_hand / rec.product_id.bundle_quantity
                rec.bundle_display = (
                    f"{rec.quantity_on_hand:.0f} {rec.product_id.uom_id.name} "
                    f"({rec.quantity_in_bundles:.1f} {rec.product_id.bundle_uom_id.name})"
                )
            else:
                rec.quantity_in_bundles = 0.0
                rec.bundle_display = f"{rec.quantity_on_hand:.0f} {rec.product_id.uom_id.name}"

    @api.depends('quantity_on_hand', 'product_id.cost_price', 'product_id.product_type', 'location_id')
    def _compute_total_value(self):
        for rec in self:
            if rec.product_id.product_type == 'asset':
                # Get all assets at this location (available + assigned)
                assets = self.env['una.asset'].search([
                    ('product_id', '=', rec.product_id.id),
                    ('current_location', '=', rec.location_id.id),
                    ('status', 'in', ['available', 'assigned'])
                ])
                if assets:
                    rec.total_value = sum(assets.mapped('cost_price')) or 0.0
                else:
                    rec.total_value = rec.quantity_on_hand * (rec.product_id.cost_price or 0.0)
            else:
                rec.total_value = rec.quantity_on_hand * (rec.product_id.cost_price or 0.0)

    # === CONSTRAINTS ===
    @api.constrains('quantity_on_hand')
    def _check_negative_stock(self):
        for rec in self:
            if rec.quantity_on_hand < 0:
                raise ValidationError('Quantity on hand cannot be negative!')

    @api.constrains('reserved_quantity')
    def _check_negative_reserved(self):
        for rec in self:
            if rec.reserved_quantity < 0:
                raise ValidationError('Reserved quantity cannot be negative!')

    def _recalculate_from_assets(self):
        for rec in self:
            if rec.product_id.product_type == 'asset':
                # Count available assets at this location
                available_count = self.env['una.asset'].search_count([
                    ('product_id', '=', rec.product_id.id),
                    ('current_location', '=', rec.location_id.id),
                    ('status', '=', 'available')
                ])

                # Count assigned assets at this location
                assigned_count = self.env['una.asset'].search_count([
                    ('product_id', '=', rec.product_id.id),
                    ('current_location', '=', rec.location_id.id),
                    ('status', '=', 'assigned')
                ])

                rec.quantity_on_hand = available_count
                rec.reserved_quantity = assigned_count

    # === OVERRIDE CREATE TO PREVENT MANUAL ASSET INVENTORY ===
    @api.model
    def create(self, vals):
        # Check if this is a manual creation for an asset product
        if vals.get('product_id'):
            product = self.env['una.product'].browse(vals['product_id'])
            if product and product.product_type == 'asset':
                # For assets, don't allow manual creation
                # Check if inventory already exists for this product/location
                existing = self.search([
                    ('product_id', '=', vals['product_id']),
                    ('location_id', '=', vals.get('location_id'))
                ])
                if existing:
                    # Return existing record instead of creating new
                    return existing
                else:
                    # Create with calculated values from assets
                    available_count = self.env['una.asset'].search_count([
                        ('product_id', '=', vals['product_id']),
                        ('current_location', '=', vals.get('location_id')),
                        ('status', '=', 'available')
                    ])
                    assigned_count = self.env['una.asset'].search_count([
                        ('product_id', '=', vals['product_id']),
                        ('current_location', '=', vals.get('location_id')),
                        ('status', '=', 'assigned')
                    ])
                    vals['quantity_on_hand'] = available_count
                    vals['reserved_quantity'] = assigned_count
        return super().create(vals)

    @api.model
    def _cron_recalculate_asset_inventory(self):
        asset_inventory = self.search([
            ('product_id.product_type', '=', 'asset')
        ])

        for rec in asset_inventory:
            rec._recalculate_from_assets()

        # Also create inventory records for assets that don't have them
        all_assets = self.env['una.asset'].search([
            ('status', 'in', ['available', 'assigned'])
        ])

        for asset in all_assets:
            if asset.current_location:
                inv = self.search([
                    ('product_id', '=', asset.product_id.id),
                    ('location_id', '=', asset.current_location.id)
                ])
                if not inv:
                    # Count all assets at this location
                    available_count = self.env['una.asset'].search_count([
                        ('product_id', '=', asset.product_id.id),
                        ('current_location', '=', asset.current_location.id),
                        ('status', '=', 'available')
                    ])
                    assigned_count = self.env['una.asset'].search_count([
                        ('product_id', '=', asset.product_id.id),
                        ('current_location', '=', asset.current_location.id),
                        ('status', '=', 'assigned')
                    ])
                    self.create({
                        'product_id': asset.product_id.id,
                        'location_id': asset.current_location.id,
                        'quantity_on_hand': available_count,
                        'reserved_quantity': assigned_count,
                    })