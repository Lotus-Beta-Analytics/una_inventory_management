# from odoo import models, fields, api
# from odoo.exceptions import UserError, ValidationError
# from datetime import timedelta
#
#
# class UnaStockCount(models.Model):
#     _name = 'una.stock.count'
#     _description = 'UNA Stock Count'
#     _rec_name = 'name'
#     _order = 'create_date desc'
#     _inherit = ['mail.thread', 'mail.activity.mixin']
#
#     # === BASIC FIELDS ===
#     name = fields.Char(string='Reference', readonly=True, default='New')
#     date = fields.Date(string='Count Date', default=fields.Date.today, required=True)
#     scheduled_date = fields.Date(string='Scheduled Date', default=fields.Date.today)
#     completed_date = fields.Datetime(string='Completed Date')
#
#     location_id = fields.Many2one(
#         'una.location',
#         string='Location',
#         required=True,
#         help="Location being counted"
#     )
#
#     # === STATUS ===
#     state = fields.Selection([
#         ('draft', 'Draft'),
#         ('in_progress', 'In Progress'),
#         ('confirmed', 'Confirmed'),
#         ('cancelled', 'Cancelled')
#     ], string='Status', default='draft', tracking=True)
#
#     # === LINES ===
#     line_ids = fields.One2many('una.stock.count.line', 'count_id', string='Count Lines')
#
#     # === SUMMARY ===
#     total_lines = fields.Integer(string='Total Lines', compute='_compute_summary')
#     total_variance = fields.Float(string='Total Variance', compute='_compute_summary')
#     has_discrepancy = fields.Boolean(string='Has Discrepancy', compute='_compute_summary')
#     total_expected_value = fields.Monetary(
#         string='Total Expected Value',
#         currency_field='currency_id',
#         compute='_compute_summary',
#         store=False
#     )
#     total_actual_value = fields.Monetary(
#         string='Total Actual Value',
#         currency_field='currency_id',
#         compute='_compute_summary',
#         store=False
#     )
#
#     currency_id = fields.Many2one(
#         'res.currency',
#         string='Currency',
#         default=lambda self: self.env.company.currency_id
#     )
#
#     # === METADATA ===
#     created_by = fields.Many2one('res.users', string='Created By', default=lambda self: self.env.user)
#     note = fields.Text(string='Note')
#
#     # === COMPUTES ===
#     @api.depends('line_ids', 'line_ids.difference', 'line_ids.expected_quantity', 'line_ids.actual_quantity')
#     def _compute_summary(self):
#         for count in self:
#             count.total_lines = len(count.line_ids)
#             count.total_variance = sum(count.line_ids.mapped('difference'))
#             count.has_discrepancy = any(line.difference != 0 for line in count.line_ids)
#             count.total_expected_value = sum(line.expected_value for line in count.line_ids)
#             count.total_actual_value = sum(line.actual_value for line in count.line_ids)
#
#     # === SEQUENCE ===
#     @api.model
#     def create(self, vals):
#         if vals.get('name', 'New') == 'New':
#             vals['name'] = self.env['ir.sequence'].next_by_code('una.stock.count') or 'New'
#         return super().create(vals)
#
#     @api.onchange('product_id')
#     def _onchange_product_id(self):
#         if self.product_id and self.count_id and self.count_id.location_id:
#             inventory = self.env['una.inventory'].search([
#                 ('product_id', '=', self.product_id.id),
#                 ('location_id', '=', self.count_id.location_id.id)
#             ], limit=1)
#             if inventory:
#                 self.expected_quantity = inventory.quantity_on_hand
#             else:
#                 self.expected_quantity = 0.0
#
#     # # === ACTIONS ===
#     # def action_start_count(self):
#     #     """Start stock count - create lines from inventory"""
#     #     for count in self:
#     #         if count.state != 'draft':
#     #             raise UserError('Only draft counts can be started!')
#     #
#     #         # Get all inventory at this location (including zero stock for completeness)
#     #         inventory = self.env['una.inventory'].search([
#     #             ('location_id', '=', count.location_id.id)
#     #         ])
#     #
#     #         if not inventory:
#     #             raise UserError('No inventory found at this location!')
#     #
#     #         # Create count lines
#     #         for inv in inventory:
#     #             self.env['una.stock.count.line'].create({
#     #                 'count_id': count.id,
#     #                 'product_id': inv.product_id.id,
#     #                 'expected_quantity': inv.quantity_on_hand,
#     #                 'actual_quantity': 0.0,
#     #             })
#     #
#     #         count.state = 'in_progress'
#     #         count.message_post(body=f"✅ Stock count started for {count.location_id.name}")
#
#     def action_start_count(self):
#         for count in self:
#             if count.state != 'draft':
#                 raise UserError('Only draft counts can be started!')
#
#             inventory = self.env['una.inventory'].search([
#                 ('location_id', '=', count.location_id.id)
#             ])
#
#             if not inventory:
#                 raise UserError('No inventory found at this location!')
#
#             for inv in inventory:
#                 expected_qty = inv.quantity_on_hand
#
#                 # ★ For assets, count actual assets (available + assigned)
#                 if inv.product_id.product_type == 'asset':
#                     asset_count = self.env['una.asset'].search_count([
#                         ('product_id', '=', inv.product_id.id),
#                         ('current_location', '=', count.location_id.id),
#                         ('status', 'in', ['available', 'assigned'])
#                     ])
#                     if asset_count > 0:
#                         expected_qty = asset_count
#
#                 self.env['una.stock.count.line'].create({
#                     'count_id': count.id,
#                     'product_id': inv.product_id.id,
#                     'expected_quantity': expected_qty,
#                     'actual_quantity': 0.0,
#                 })
#
#             count.state = 'in_progress'
#             count.message_post(body=f"✅ Stock count started for {count.location_id.name}")
#
#     def action_confirm_count(self):
#         for count in self:
#             if count.state != 'in_progress':
#                 raise UserError('Only in-progress counts can be confirmed!')
#
#             for line in count.line_ids:
#                 if line.difference != 0:
#                     inventory = self.env['una.inventory'].search([
#                         ('product_id', '=', line.product_id.id),
#                         ('location_id', '=', count.location_id.id)
#                     ])
#
#                     if inventory:
#                         old_qty = inventory.quantity_on_hand
#                         inventory.quantity_on_hand = line.actual_quantity
#
#                         inventory.message_post(
#                             body=f"📊 Stock count adjustment: {line.product_id.name} "
#                                  f"changed from {old_qty} to {line.actual_quantity} "
#                                  f"(Difference: {line.difference})"
#                         )
#                     else:
#                         # Create inventory if it doesn't exist
#                         self.env['una.inventory'].create({
#                             'product_id': line.product_id.id,
#                             'location_id': count.location_id.id,
#                             'quantity_on_hand': line.actual_quantity,
#                         })
#
#             count.state = 'confirmed'
#             count.completed_date = fields.Datetime.now()
#
#             if count.has_discrepancy:
#                 count.message_post(
#                     body=f"⚠️ Stock count completed with discrepancies: {count.total_variance} total variance"
#                 )
#             else:
#                 count.message_post(body="✅ Stock count completed with NO discrepancies")
#
#     def action_cancel(self):
#         """Cancel stock count"""
#         for count in self:
#             if count.state == 'confirmed':
#                 raise UserError('Cannot cancel a confirmed count!')
#             count.state = 'cancelled'
#             count.message_post(body="❌ Stock count cancelled")
#
#     # === WEEKLY AUTO-CREATE ===
#     @api.model
#     def _cron_create_weekly_stock_counts(self):
#         """Create stock counts for all active locations (Friday)"""
#         locations = self.env['una.location'].search([('active', '=', True)])
#
#         for location in locations:
#             # Check if count already exists for this week
#             week_start = fields.Date.today() - timedelta(days=7)
#             existing = self.search([
#                 ('location_id', '=', location.id),
#                 ('create_date', '>=', week_start),
#                 ('state', '!=', 'cancelled')
#             ])
#
#             if not existing:
#                 self.create({
#                     'location_id': location.id,
#                     'scheduled_date': fields.Date.today(),
#                     'note': 'Weekly scheduled stock count',
#                 })
#
#
# class UnaStockCountLine(models.Model):
#     _name = 'una.stock.count.line'
#     _description = 'UNA Stock Count Line'
#     _rec_name = 'product_id'
#
#     count_id = fields.Many2one('una.stock.count', string='Count', required=True)
#     product_id = fields.Many2one('una.product', string='Product', required=True)
#
#     expected_quantity = fields.Float(
#         string='Expected Quantity',
#         default=0.0,
#         digits='Product Unit of Measure'
#     )
#
#     actual_quantity = fields.Float(
#         string='Actual Quantity',
#         default=0.0,
#         digits='Product Unit of Measure'
#     )
#
#     difference = fields.Float(
#         string='Variance',
#         compute='_compute_difference',
#         digits='Product Unit of Measure'
#     )
#
#     # Value calculations
#     expected_value = fields.Monetary(
#         string='Expected Value',
#         currency_field='currency_id',
#         compute='_compute_values',
#         store=False,
#         help="Expected Quantity × Product Cost"
#     )
#
#     actual_value = fields.Monetary(
#         string='Actual Value',
#         currency_field='currency_id',
#         compute='_compute_values',
#         store=False,
#         help="Actual Quantity × Product Cost"
#     )
#
#     variance_value = fields.Monetary(
#         string='Variance Value',
#         currency_field='currency_id',
#         compute='_compute_values',
#         store=False,
#         help="Difference × Product Cost"
#     )
#
#     currency_id = fields.Many2one(
#         'res.currency',
#         string='Currency',
#         default=lambda self: self.env.company.currency_id
#     )
#
#     note = fields.Text(string='Note')
#
#     # === COMPUTES ===
#     @api.depends('expected_quantity', 'actual_quantity')
#     def _compute_difference(self):
#         for line in self:
#             line.difference = line.actual_quantity - line.expected_quantity
#
#     @api.depends('expected_quantity', 'actual_quantity', 'product_id.cost_price')
#     def _compute_values(self):
#         for line in self:
#             cost = line.product_id.cost_price or 0.0
#             line.expected_value = line.expected_quantity * cost
#             line.actual_value = line.actual_quantity * cost
#             line.variance_value = line.difference * cost
#
#     # === CONSTRAINTS ===
#     @api.constrains('actual_quantity')
#     def _check_actual_quantity(self):
#         for line in self:
#             if line.actual_quantity < 0:
#                 raise ValidationError('Actual quantity cannot be negative!')
#
#     @api.onchange('product_id')
#     def _onchange_product_id(self):
#         if self.product_id and self.count_id and self.count_id.location_id:
#             inventory = self.env['una.inventory'].search([
#                 ('product_id', '=', self.product_id.id),
#                 ('location_id', '=', self.count_id.location_id.id)
#             ], limit=1)
#             if inventory:
#                 self.expected_quantity = inventory.quantity_on_hand
#             else:
#                 self.expected_quantity = 0.0

from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError
from datetime import timedelta


class UnaStockCount(models.Model):
    _name = 'una.stock.count'
    _description = 'UNA Stock Count'
    _rec_name = 'name'
    _order = 'create_date desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    # === BASIC FIELDS ===
    name = fields.Char(string='Reference', readonly=True, default='New')
    date = fields.Date(string='Count Date', default=fields.Date.today, required=True)
    scheduled_date = fields.Date(string='Scheduled Date', default=fields.Date.today)
    completed_date = fields.Datetime(string='Completed Date')

    location_id = fields.Many2one(
        'una.location',
        string='Location',
        required=True,
        help="Location being counted"
    )

    # === STATUS ===
    state = fields.Selection([
        ('draft', 'Draft'),
        ('in_progress', 'In Progress'),
        ('confirmed', 'Confirmed'),
        ('cancelled', 'Cancelled')
    ], string='Status', default='draft', tracking=True)

    # === LINES ===
    line_ids = fields.One2many('una.stock.count.line', 'count_id', string='Count Lines')

    # === SUMMARY ===
    total_lines = fields.Integer(string='Total Lines', compute='_compute_summary')
    total_variance = fields.Float(string='Total Variance', compute='_compute_summary')
    has_discrepancy = fields.Boolean(string='Has Discrepancy', compute='_compute_summary')
    total_expected_value = fields.Monetary(
        string='Total Expected Value',
        currency_field='currency_id',
        compute='_compute_summary',
        store=False
    )
    total_actual_value = fields.Monetary(
        string='Total Actual Value',
        currency_field='currency_id',
        compute='_compute_summary',
        store=False
    )

    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id
    )

    # === METADATA ===
    created_by = fields.Many2one('res.users', string='Created By', default=lambda self: self.env.user)
    note = fields.Text(string='Note')

    # === COMPUTES ===
    @api.depends('line_ids', 'line_ids.difference', 'line_ids.expected_quantity', 'line_ids.actual_quantity')
    def _compute_summary(self):
        for count in self:
            count.total_lines = len(count.line_ids)
            count.total_variance = sum(count.line_ids.mapped('difference'))
            count.has_discrepancy = any(line.difference != 0 for line in count.line_ids)
            count.total_expected_value = sum(line.expected_value for line in count.line_ids)
            count.total_actual_value = sum(line.actual_value for line in count.line_ids)

    # === SEQUENCE ===
    @api.model
    def create(self, vals):
        if vals.get('name', 'New') == 'New':
            vals['name'] = self.env['ir.sequence'].next_by_code('una.stock.count') or 'New'
        return super().create(vals)

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id and self.count_id and self.count_id.location_id:
            inventory = self.env['una.inventory'].search([
                ('product_id', '=', self.product_id.id),
                ('location_id', '=', self.count_id.location_id.id)
            ], limit=1)
            if inventory:
                self.expected_quantity = inventory.quantity_on_hand
            else:
                self.expected_quantity = 0.0

    # === ACTIONS ===
    def action_start_count(self):
        for count in self:
            if count.state != 'draft':
                raise UserError('Only draft counts can be started!')

            # ================================================================
            # === 1. Get inventory for CONSUMABLES at this location ===
            # ================================================================
            inventory = self.env['una.inventory'].search([
                ('location_id', '=', count.location_id.id)
            ])

            for inv in inventory:
                self.env['una.stock.count.line'].create({
                    'count_id': count.id,
                    'product_id': inv.product_id.id,
                    'expected_quantity': inv.quantity_on_hand,
                    'actual_quantity': 0.0,
                    'is_asset': False,
                })

            # ================================================================
            # === 2. Get ASSETS at this location (individual tracking) ===
            # ================================================================
            assets = self.env['una.asset'].search([
                ('current_location', '=', count.location_id.id),
                ('status', 'in', ['available', 'assigned'])
            ])

            for asset in assets:
                # Check if we already have a line for this asset
                existing_line = self.env['una.stock.count.line'].search([
                    ('count_id', '=', count.id),
                    ('product_id', '=', asset.product_id.id),
                    ('is_asset', '=', True),
                    ('asset_id', '=', asset.id)
                ])

                if not existing_line:
                    self.env['una.stock.count.line'].create({
                        'count_id': count.id,
                        'product_id': asset.product_id.id,
                        'asset_id': asset.id,
                        'serial_number': asset.serial_number,
                        'expected_quantity': 1,
                        'actual_quantity': 1,  # Default to found (user can change to 0 if missing)
                        'is_asset': True,
                        'note': f"Asset: {asset.serial_number}",
                    })

            if not inventory and not assets:
                raise UserError('No inventory or assets found at this location!')

            count.state = 'in_progress'
            count.message_post(
                body=f"✅ Stock count started for {count.location_id.name} "
                     f"({len(inventory)} inventory lines, {len(assets)} assets)"
            )

    def action_confirm_count(self):
        for count in self:
            if count.state != 'in_progress':
                raise UserError('Only in-progress counts can be confirmed!')

            for line in count.line_ids:
                if line.difference != 0:
                    # Skip asset lines - they don't use inventory
                    if line.is_asset:
                        # For assets, update the asset status if missing
                        if line.actual_quantity == 0 and line.asset_id:
                            line.asset_id.write({
                                'status': 'missing',
                                'last_move_date': fields.Datetime.now(),
                            })
                            count.message_post(
                                body=f"⚠️ Asset {line.serial_number} marked as MISSING in stock count"
                            )
                        continue

                    # For consumables, update inventory
                    inventory = self.env['una.inventory'].search([
                        ('product_id', '=', line.product_id.id),
                        ('location_id', '=', count.location_id.id)
                    ])

                    if inventory:
                        old_qty = inventory.quantity_on_hand
                        inventory.quantity_on_hand = line.actual_quantity

                        inventory.message_post(
                            body=f"📊 Stock count adjustment: {line.product_id.name} "
                                 f"changed from {old_qty} to {line.actual_quantity} "
                                 f"(Difference: {line.difference})"
                        )
                    else:
                        # Create inventory if it doesn't exist
                        self.env['una.inventory'].create({
                            'product_id': line.product_id.id,
                            'location_id': count.location_id.id,
                            'quantity_on_hand': line.actual_quantity,
                        })

            count.state = 'confirmed'
            count.completed_date = fields.Datetime.now()

            if count.has_discrepancy:
                count.message_post(
                    body=f"⚠️ Stock count completed with discrepancies: {count.total_variance} total variance"
                )
            else:
                count.message_post(body="✅ Stock count completed with NO discrepancies")

    def action_cancel(self):
        """Cancel stock count"""
        for count in self:
            if count.state == 'confirmed':
                raise UserError('Cannot cancel a confirmed count!')
            count.state = 'cancelled'
            count.message_post(body="❌ Stock count cancelled")

    # === WEEKLY AUTO-CREATE ===
    @api.model
    def _cron_create_weekly_stock_counts(self):
        """Create stock counts for all active locations (Friday)"""
        locations = self.env['una.location'].search([('active', '=', True)])

        for location in locations:
            # Check if count already exists for this week
            week_start = fields.Date.today() - timedelta(days=7)
            existing = self.search([
                ('location_id', '=', location.id),
                ('create_date', '>=', week_start),
                ('state', '!=', 'cancelled')
            ])

            if not existing:
                self.create({
                    'location_id': location.id,
                    'scheduled_date': fields.Date.today(),
                    'note': 'Weekly scheduled stock count',
                })


class UnaStockCountLine(models.Model):
    _name = 'una.stock.count.line'
    _description = 'UNA Stock Count Line'
    _rec_name = 'product_id'

    count_id = fields.Many2one('una.stock.count', string='Count', required=True)
    product_id = fields.Many2one('una.product', string='Product', required=True)

    # === ASSET TRACKING ===
    asset_id = fields.Many2one('una.asset', string='Asset')
    serial_number = fields.Char(string='Serial Number', related='asset_id.serial_number', store=True)
    is_asset = fields.Boolean(string='Is Asset', default=False)

    expected_quantity = fields.Float(
        string='Expected Quantity',
        default=0.0,
        digits='Product Unit of Measure'
    )

    actual_quantity = fields.Float(
        string='Actual Quantity',
        default=0.0,
        digits='Product Unit of Measure'
    )

    difference = fields.Float(
        string='Variance',
        compute='_compute_difference',
        digits='Product Unit of Measure'
    )

    # Value calculations
    expected_value = fields.Monetary(
        string='Expected Value',
        currency_field='currency_id',
        compute='_compute_values',
        store=False,
        help="Expected Quantity × Product Cost"
    )

    actual_value = fields.Monetary(
        string='Actual Value',
        currency_field='currency_id',
        compute='_compute_values',
        store=False,
        help="Actual Quantity × Product Cost"
    )

    variance_value = fields.Monetary(
        string='Variance Value',
        currency_field='currency_id',
        compute='_compute_values',
        store=False,
        help="Difference × Product Cost"
    )

    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id
    )

    note = fields.Text(string='Note')

    # === COMPUTES ===
    @api.depends('expected_quantity', 'actual_quantity')
    def _compute_difference(self):
        for line in self:
            line.difference = line.actual_quantity - line.expected_quantity

    @api.depends('expected_quantity', 'actual_quantity', 'product_id.cost_price')
    def _compute_values(self):
        for line in self:
            cost = line.product_id.cost_price or 0.0
            line.expected_value = line.expected_quantity * cost
            line.actual_value = line.actual_quantity * cost
            line.variance_value = line.difference * cost

    # === CONSTRAINTS ===
    @api.constrains('actual_quantity')
    def _check_actual_quantity(self):
        for line in self:
            if line.actual_quantity < 0:
                raise ValidationError('Actual quantity cannot be negative!')

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id and self.count_id and self.count_id.location_id:
            if self.is_asset:
                # For assets, expected quantity is 1
                self.expected_quantity = 1
            else:
                inventory = self.env['una.inventory'].search([
                    ('product_id', '=', self.product_id.id),
                    ('location_id', '=', self.count_id.location_id.id)
                ], limit=1)
                if inventory:
                    self.expected_quantity = inventory.quantity_on_hand
                else:
                    self.expected_quantity = 0.0