from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError
import re
import logging

_logger = logging.getLogger(__name__)


class UnaStockMove(models.Model):
    _name = 'una.stock.move'
    _description = 'UNA Stock Move'
    _rec_name = 'reference'
    _order = 'create_date desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    reference = fields.Char(string='Reference', readonly=True, default='New')
    product_id = fields.Many2one('una.product', string='Product', required=True)

    product_type = fields.Selection(
        related='product_id.product_type',
        string='Product Type',
        store=True
    )

    is_serial_tracked = fields.Boolean(
        string='Is Serial Tracked',
        compute='_compute_is_serial_tracked',
        store=True
    )

    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        help="Employee the asset is being issued to"
    )

    move_type = fields.Selection([
        ('receipt', 'Receipt'),
        ('issue', 'Issue'),
        ('transfer', 'Transfer'),
        ('scrap', 'Scrap'),
        ('adjustment', 'Adjustment')
    ], string='Move Type', required=True)

    quantity = fields.Float(string='Quantity', required=True, default=1.0)

    is_bundle_move = fields.Boolean(
        string='Is Bundle Move',
        compute='_compute_bundle_fields',
        store=False,
    )

    quantity_in_bundles = fields.Float(
        string='Bundles',
        compute='_compute_bundle_fields',
        store=False,
    )

    quantity_in_units = fields.Float(
        string='Total Units',
        compute='_compute_bundle_fields',
        store=False,
    )

    # ✅ These are the fields used in your view
    bundle_uom_id = fields.Many2one(
        'uom.uom',
        string='Bundle UOM',
        related='product_id.bundle_uom_id',
        readonly=True,
    )

    bundle_quantity = fields.Float(
        string='Units per Bundle',
        related='product_id.bundle_quantity',
        readonly=True,
    )

    @api.depends('product_id', 'quantity')
    def _compute_bundle_fields(self):
        for move in self:
            if move.product_id and move.product_id.is_bundle and move.product_id.bundle_quantity > 0:
                move.is_bundle_move = True
                move.quantity_in_bundles = move.quantity / move.product_id.bundle_quantity
                move.quantity_in_units = move.quantity
            else:
                move.is_bundle_move = False
                move.quantity_in_bundles = 0.0
                move.quantity_in_units = move.quantity

    source_location = fields.Many2one(
        'una.location',
        string='Moving From',
        help="Auto-set from selected asset for Issue/Transfer/Scrap"
    )

    destination_location = fields.Many2one(
        'una.location',
        string='Moving To'
    )

    move_date = fields.Datetime(string='Date', default=fields.Datetime.now)

    cost_price_at_move = fields.Monetary(
        string='Cost at Move',
        currency_field='currency_id',
        default=1.0
    )

    total_cost = fields.Monetary(
        string='Total Cost',
        currency_field='currency_id',
        compute='_compute_total_cost',
        store=True,
        help="Total cost = Cost at Move × Quantity"
    )

    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id
    )

    description = fields.Text(string='Description')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('cancelled', 'Cancelled')
    ], string='Status', default='draft', tracking=True)

    # === ASSET SELECTION (Only Available Assets) ===
    selected_asset_ids = fields.Many2many(
        'una.asset',
        string='Select Asset',
        domain="[('product_id', '=', product_id), ('status', '=', 'available')]",
        help="Select the asset(s) to move."
    )

    # === AUTO SOURCE LOCATION (STORED at confirmation) ===
    auto_source_location = fields.Char(
        string="Asset's Current Location",
        compute='_compute_auto_source_location',
        store=True,
        help="Shows the current location of the selected asset at the time of confirmation"
    )

    # === SERIAL NUMBER FIELDS ===
    serial_entry_method = fields.Selection([
        ('single', 'Enter One by One'),
        ('range', 'Generate from First SN')
    ], string='Serial Entry Method', default='single')

    serial_numbers = fields.Text(
        string='Serial Numbers',
        help="Enter serial numbers, one per line"
    )

    first_serial_number = fields.Char(
        string='First Serial Number',
        help="Enter first serial number. System will generate the rest."
    )

    generated_serials = fields.Text(
        string='Generated Serial Numbers',
        compute='_compute_generated_serials',
        store=False
    )

    requisition_id = fields.Many2one('una.requisition', string='Requisition')

    purchase_picking_id = fields.Many2one(
        'stock.picking',
        string='Source Purchase Receipt',
        readonly=True,
        help="The original stock picking from the purchase order"
    )
    purchase_order_id = fields.Many2one(
        'purchase.order',
        string='Source Purchase Order',
        readonly=True,
        help="The original purchase order"
    )
    odoo_product_id = fields.Many2one(
        'product.product',
        string='Odoo Product',
        readonly=True,
        help="The original Odoo product"
    )
    is_auto_created = fields.Boolean(
        string='Auto Created from Purchase',
        default=False,
        help='Created automatically from purchase order receipt'
    )

    @api.depends('product_id')
    def _compute_is_serial_tracked(self):
        for move in self:
            if move.product_id:
                move.is_serial_tracked = move.product_id.is_serial_tracked
            else:
                move.is_serial_tracked = False

    @api.depends('first_serial_number', 'quantity')
    def _compute_generated_serials(self):
        for move in self:
            if move.serial_entry_method == 'range' and move.first_serial_number and move.quantity > 0:
                serials = move._generate_serial_range(move.first_serial_number, int(move.quantity))
                move.generated_serials = '\n'.join(serials)
            else:
                move.generated_serials = ''

    @api.depends('selected_asset_ids', 'move_type', 'product_type', 'state')
    def _compute_auto_source_location(self):
        for move in self:
            if move.state == 'draft' and move.move_type in ['issue', 'transfer',
                                                            'scrap'] and move.product_id.product_type == 'asset' and move.selected_asset_ids:
                asset = move.selected_asset_ids[0]
                move.auto_source_location = asset.current_location.name if asset.current_location else 'No location set'
            elif move.state == 'confirmed' and move.auto_source_location:
                pass
            else:
                move.auto_source_location = False

    @api.depends('cost_price_at_move', 'quantity')
    def _compute_total_cost(self):
        for move in self:
            if move.cost_price_at_move and move.quantity:
                move.total_cost = move.cost_price_at_move * move.quantity
            else:
                move.total_cost = 0.0

    def _generate_serial_range(self, first_serial, quantity):
        """Generate serial numbers from first serial and quantity"""
        serials = []
        match = re.match(r'^(.*?)(\d+)$', first_serial)

        if match:
            prefix = match.group(1)
            start_num = int(match.group(2))
            num_length = len(match.group(2))

            for i in range(quantity):
                serial_num = start_num + i
                serial = f"{prefix}{str(serial_num).zfill(num_length)}"
                serials.append(serial)
        else:
            for i in range(quantity):
                serials.append(f"{first_serial}-{str(i + 1).zfill(3)}")

        return serials

    @api.model
    def create(self, vals):
        if vals.get('reference', 'New') == 'New':
            vals['reference'] = self.env['ir.sequence'].next_by_code('una.stock.move') or 'New'
        return super().create(vals)

    # ================================================================
    # SEQUENCE FOR STOCK MOVES
    # ================================================================
    def _get_move_prefix(self):
        """Get prefix based on move type"""
        prefix_map = {
            'receipt': 'RCT',
            'issue': 'ISS',
            'transfer': 'TRF',
            'scrap': 'SCR',
            'adjustment': 'ADJ'
        }
        return prefix_map.get(self.move_type, 'MOV')

    def _get_sequence_code(self):
        """Get sequence code based on move type"""
        seq_map = {
            'receipt': 'una.stock.move.receipt',
            'issue': 'una.stock.move.issue',
            'transfer': 'una.stock.move.transfer',
            'scrap': 'una.stock.move.scrap',
            'adjustment': 'una.stock.move.adjustment'
        }
        return seq_map.get(self.move_type, 'una.stock.move')

    def _get_admin_email(self):
        """Get admin team emails"""
        self.ensure_one()
        admin_emails = []

        # Get Admin Assistant users
        admin_assistants = self.env['res.users'].search([
            ('groups_id', 'in', self.env.ref('una_inventory_management.group_una_admin_assistant').id),
            ('active', '=', True)
        ])

        for user in admin_assistants:
            if user.email:
                admin_emails.append(user.email)
            elif user.partner_id and user.partner_id.email:
                admin_emails.append(user.partner_id.email)

        # Get Admin Manager users
        admin_managers = self.env['res.users'].search([
            ('groups_id', 'in', self.env.ref('una_inventory_management.group_una_admin_manager').id),
            ('active', '=', True)
        ])

        for user in admin_managers:
            if user.email:
                admin_emails.append(user.email)
            elif user.partner_id and user.partner_id.email:
                admin_emails.append(user.partner_id.email)

        return ', '.join(set(admin_emails)) or self.env.company.email or 'no-reply@flyunitednigeria.com'

    def _get_admin_manager_email(self):
        """Get Admin Manager emails for CC"""
        self.ensure_one()
        admin_emails = []

        # Get Admin Manager users
        admin_managers = self.env['res.users'].search([
            ('groups_id', 'in', self.env.ref('una_inventory_management.group_una_admin_manager').id),
            ('active', '=', True)
        ])

        for user in admin_managers:
            if user.email:
                admin_emails.append(user.email)
            elif user.partner_id and user.partner_id.email:
                admin_emails.append(user.partner_id.email)

        unique_emails = list(set(admin_emails))
        return ', '.join(unique_emails) if unique_emails else ''

    def _get_receipt_url(self):
        self.ensure_one()
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        return f"{base_url}/web#id={self.id}&model=una.stock.move&view_type=form"

    def action_confirm(self):
        _logger.info("=" * 60)
        _logger.info("🔴🔴🔴 action_confirm STARTED 🔴🔴🔴")
        _logger.info("=" * 60)

        for move in self:
            _logger.info(f"🔴 Processing move: {move.id}")
            _logger.info(f"  Product: {move.product_id.name if move.product_id else 'None'}")
            _logger.info(f"  Move Type: {move.move_type}")
            _logger.info(f"  Product Type: {move.product_type}")
            _logger.info(f"  State: {move.state}")
            _logger.info(f"  Quantity: {move.quantity}")
            _logger.info(f"  Source: {move.source_location.name if move.source_location else 'None'}")
            _logger.info(f"  Destination: {move.destination_location.name if move.destination_location else 'None'}")

            # ================================================================
            # === CONSUMABLE: Validate inventory and process ===
            # ================================================================
            if move.move_type in ['issue', 'transfer', 'scrap'] and move.product_type == 'consumable':
                _logger.info("📌 CONSUMABLE: Processing consumable issue/transfer/scrap")

                if move.source_location:
                    # Check inventory at the source location
                    inventory = self.env['una.inventory'].search([
                        ('product_id', '=', move.product_id.id),
                        ('location_id', '=', move.source_location.id)
                    ], limit=1)

                    _logger.info(f"  Inventory found: {inventory.quantity_on_hand if inventory else 'None'}")
                    _logger.info(f"  Available quantity: {inventory.available_quantity if inventory else '0'}")

                    if inventory and inventory.quantity_on_hand > 0:
                        if inventory.quantity_on_hand < move.quantity:
                            raise ValidationError(
                                f"❌ Insufficient Stock at '{move.source_location.name}'\n\n"
                                f"Available (On Hand): {inventory.quantity_on_hand} units\n"
                                f"Requested: {move.quantity} units\n\n"
                                f"💡 Reduce quantity or receive more stock."
                            )

                        # ✅ Check if available quantity (on_hand - reserved) is sufficient
                        if inventory.available_quantity < move.quantity:
                            raise ValidationError(
                                f"❌ Insufficient Available Stock at '{move.source_location.name}'\n\n"
                                f"On Hand: {inventory.quantity_on_hand} units\n"
                                f"Reserved: {inventory.reserved_quantity} units\n"
                                f"Available: {inventory.available_quantity} units\n"
                                f"Requested: {move.quantity} units\n\n"
                                f"💡 Some stock is reserved for other orders. Please reduce quantity or wait for more stock."
                            )

                        move.message_post(
                            body=f"📍 Found {inventory.quantity_on_hand} {move.product_id.name} at {move.source_location.name} "
                                 f"(Available: {inventory.available_quantity})"
                        )

                    else:
                        raise UserError(
                            f"❌ No Stock at '{move.source_location.name}'\n\n"
                            f"The inventory at this location is no longer available.\n"
                            f"This may have been issued to someone else.\n\n"
                            f"💡 Please check inventory levels and try again."
                        )
                else:
                    raise ValidationError(
                        f"⚠️ Source Location Required\n\n"
                        f"You must select a 'Moving From' location for {move.product_id.name}.\n"
                        f"This tells the system where to take the stock from.\n\n"
                        f"📝 Please select a source location and try again."
                    )

                # ✅ REMOVED: The early confirmation code and continue statement
                # The move will be confirmed at the end of the loop with all other moves

            # ================================================================
            # === ASSET: Validation and auto-set ===
            # ================================================================
            if move.move_type in ['issue', 'transfer', 'scrap'] and move.product_id.product_type == 'asset':
                _logger.info("📌 ASSET: Processing asset move")

                if not move.selected_asset_ids:
                    raise ValidationError(f'Please select at least one asset to {move.move_type}!')

                # Auto-set quantity based on number of selected assets
                move.quantity = len(move.selected_asset_ids)

                # Check all assets have a location
                for asset in move.selected_asset_ids:
                    if not asset.current_location:
                        raise UserError(
                            f"❌ Asset Location Missing\n\n"
                            f"Asset {asset.serial_number} has no current location assigned.\n\n"
                            f"💡 Please update the asset record and assign a location first."
                        )

                # Check if assets are in different locations
                locations = move.selected_asset_ids.mapped('current_location')
                if len(locations) > 1:
                    move.message_post(
                        body=f"⚠️ Selected assets are in different locations: {', '.join(locations.mapped('name'))}."
                    )

                # Auto-set source location from the first asset
                first_asset = move.selected_asset_ids[0]
                move.auto_source_location = first_asset.current_location.name
                move.source_location = first_asset.current_location.id
                move.message_post(
                    body=f"📍 Moving From auto-set to: {first_asset.current_location.name} from {len(move.selected_asset_ids)} asset(s)"
                )

            # === VALIDATION CHECKS ===
            if move.state != 'draft':
                raise ValidationError(
                    f"❌ Invalid Move State\n\n"
                    f"This move is already {move.state}. Only draft moves can be confirmed."
                )

            if move.cost_price_at_move <= 0:
                raise ValidationError(
                    f"❌ Invalid Cost\n\n"
                    f"Cost must be greater than zero. Current cost: {move.cost_price_at_move}\n\n"
                    f"💡 Please enter a valid cost amount and try again."
                )

            # ================================================================
            # === RECEIPT: Auto-create assets ===
            # ================================================================
            if move.move_type == 'receipt' and move.is_serial_tracked:
                _logger.info("📌 RECEIPT: Processing serial-tracked receipt")

                final_serials = []

                if move.serial_entry_method == 'single':
                    if move.serial_numbers:
                        final_serials = [s.strip() for s in move.serial_numbers.split('\n') if s.strip()]
                    if not final_serials:
                        raise ValidationError(
                            f"❌ Serial Numbers Required\n\n"
                            f"Please enter serial numbers for {move.product_id.name}.\n"
                            f"Enter one serial number per line."
                        )

                elif move.serial_entry_method == 'range':
                    if not move.first_serial_number:
                        raise ValidationError(
                            f"❌ First Serial Number Required\n\n"
                            f"Please enter the first serial number to generate the range."
                        )
                    final_serials = move._generate_serial_range(move.first_serial_number, int(move.quantity))

                if len(final_serials) != int(move.quantity):
                    raise ValidationError(
                        f"❌ Serial Number Count Mismatch\n\n"
                        f"Number of serials provided: {len(final_serials)}\n"
                        f"Quantity expected: {int(move.quantity)}\n\n"
                        f"💡 Please ensure the number of serial numbers matches the quantity."
                    )

                cost_per_asset = move.cost_price_at_move / len(final_serials)
                for serial in final_serials:
                    self.env['una.asset'].create({
                        'name': f"{move.product_id.name} - {serial}",
                        'product_id': move.product_id.id,
                        'serial_number': serial,
                        'cost_price': cost_per_asset,
                        'current_location': move.destination_location.id,
                        'source_location': move.source_location.id or False,
                        'last_move_date': fields.Datetime.now(),
                        'status': 'available',
                        'purchase_date': fields.Date.today(),
                        'stock_move_id': move.id,
                    })
                    move.message_post(body=f"📥 Asset created: {serial}")

                _logger.info(f"✅ Created {len(final_serials)} assets for receipt {move.reference}")

            # ================================================================
            # === ISSUE: Assign assets (FIXED - Preserves manual selection) ===
            # ================================================================
            if move.move_type == 'issue' and move.product_id.product_type == 'asset':
                _logger.info("📌 ASSET ISSUE: Processing asset issue")

                # ★ Check if user manually selected assets
                user_selected = bool(move.selected_asset_ids)

                if not user_selected:
                    # Only auto-select if user hasn't selected anything
                    available_assets = self.env['una.asset'].search([
                        ('product_id', '=', move.product_id.id),
                        ('status', '=', 'available')
                    ])

                    if not available_assets:
                        raise UserError(
                            f"❌ No Available Assets\n\n"
                            f"No available assets found for {move.product_id.name}.\n\n"
                            f"💡 What you can do:\n"
                            f"  • Receive assets first using a RECEIPT\n"
                            f"  • Check if assets are already assigned to someone\n"
                            f"  • Select assets manually if they exist"
                        )

                    # Check if assets are in different locations
                    locations = available_assets.mapped('current_location')

                    if len(locations) > 1:
                        move.message_post(
                            body=f"⚠️ Assets are in different locations: {', '.join(locations.mapped('name'))}. "
                                 f"Selected {len(available_assets)} assets."
                        )

                    # Auto-select all available assets (or limit to quantity if specified)
                    if move.quantity > 0 and len(available_assets) > move.quantity:
                        available_assets = available_assets[:int(move.quantity)]

                    move.selected_asset_ids = [(6, 0, available_assets.ids)]
                    move.quantity = len(available_assets)
                    move.message_post(body=f"🤖 Auto-selected {len(available_assets)} asset(s) for issue")
                else:
                    # ★ User manually selected - preserve their selection
                    move.quantity = len(move.selected_asset_ids)
                    move.message_post(
                        body=f"📝 Admin manually selected {len(move.selected_asset_ids)} asset(s) for issue"
                    )

                # ★ Use the SELECTED assets (whether auto or manual)
                selected_assets = move.selected_asset_ids

                # Check if selected assets are in different locations
                selected_locations = selected_assets.mapped('current_location')
                if len(selected_locations) > 1:
                    move.message_post(
                        body=f"⚠️ Selected assets are in different locations: {', '.join(selected_locations.mapped('name'))}. "
                             f"Each asset will keep its own source location."
                    )

                # Get employee from stock move
                employee_id = move.employee_id.id if move.employee_id else False
                employee = move.employee_id

                # ★ Track which source locations have been updated
                updated_source_locations = set()
                dest_inventory_updated = False

                for asset in selected_assets:
                    if asset.status != 'available':
                        raise ValidationError(
                            f"❌ Asset Not Available\n\n"
                            f"Asset {asset.serial_number} is no longer available.\n"
                            f"Current status: {asset.status}\n\n"
                            f"💡 Please refresh the page and try again with available assets."
                        )

                    # Store the asset's current location before updating
                    asset_source_location = asset.current_location.id
                    asset_source_location_name = asset.current_location.name

                    asset.write({
                        'status': 'assigned',
                        'assigned_date': fields.Date.today(),
                        'current_location': move.destination_location.id or asset.current_location.id,
                        'source_location': asset_source_location,
                        'last_move_date': fields.Datetime.now(),
                        'assigned_to': employee_id,
                    })

                    # ★ Update inventory - DECREASE on_hand from source (ONCE per location)
                    if asset_source_location not in updated_source_locations:
                        Inventory = self.env['una.inventory'].sudo()

                        # 1. Decrease quantity on hand from the SOURCE location
                        source_inventory = Inventory.search([
                            ('product_id', '=', move.product_id.id),
                            ('location_id', '=', asset_source_location)
                        ])

                        if source_inventory:
                            # ★ Decrease on_hand by 1 (asset was removed from this location)
                            source_inventory.quantity_on_hand -= 1
                            # ★ Increase reserved_quantity at source (asset is now reserved/assigned)
                            source_inventory.reserved_quantity += 1
                            move.message_post(
                                body=f"📍 Removed 1 {move.product_id.name} from {asset_source_location_name} "
                                     f"(On Hand: {source_inventory.quantity_on_hand}, Reserved: {source_inventory.reserved_quantity})"
                            )
                            updated_source_locations.add(asset_source_location)

                    # ★ Update destination inventory (ONCE per move)
                    if not dest_inventory_updated and move.destination_location:
                        Inventory = self.env['una.inventory'].sudo()
                        dest_inventory = Inventory.search([
                            ('product_id', '=', move.product_id.id),
                            ('location_id', '=', move.destination_location.id)
                        ])
                        if not dest_inventory:
                            dest_inventory = Inventory.create({
                                'product_id': move.product_id.id,
                                'location_id': move.destination_location.id,
                                'quantity_on_hand': 0,
                                'reserved_quantity': 0,
                            })

                        # ★ Increase reserved at destination (once for the move)
                        dest_inventory.reserved_quantity += 1
                        dest_inventory_updated = True
                        move.message_post(
                            body=f"📦 Reserved 1 {move.product_id.name} at {move.destination_location.name} "
                                 f"(Reserved: {dest_inventory.reserved_quantity})"
                        )

                    employee_name = employee.name if employee else 'N/A'
                    move.message_post(body=f"✅ Asset assigned: {asset.serial_number} to {employee_name}")

                    # Send email to employee
                    if employee and (employee.work_email or employee.user_id.email):
                        template = self.env.ref('una_inventory_management.email_template_asset_assignment',
                                                raise_if_not_found=False)
                        if template:
                            try:
                                template.send_mail(move.id, force_send=True, raise_exception=False,
                                                   email_values={
                                                       'email_to': employee.work_email or employee.user_id.email
                                                   })
                            except Exception as e:
                                move.message_post(body=f"⚠️ Email could not be sent: {str(e)}")

                _logger.info(f"✅ Assigned {len(selected_assets)} assets in move {move.reference}")

            # ================================================================
            # === TRANSFER: Move assets ===
            # ================================================================
            if move.move_type == 'transfer' and move.product_id.product_type == 'asset':
                _logger.info("📌 ASSET TRANSFER: Processing asset transfer")

                if not move.selected_asset_ids:
                    raise ValidationError('Please select at least one asset to transfer!')

                # Check if selected assets are in different locations
                selected_locations = move.selected_asset_ids.mapped('current_location')
                if len(selected_locations) > 1:
                    move.message_post(
                        body=f"⚠️ Selected assets are in different locations: {', '.join(selected_locations.mapped('name'))}. "
                             f"All assets will be transferred to {move.destination_location.name}."
                    )

                for asset in move.selected_asset_ids:
                    if asset.status != 'available':
                        raise ValidationError(
                            f"❌ Asset Not Available\n\n"
                            f"Asset {asset.serial_number} is no longer available.\n"
                            f"Current status: {asset.status}\n\n"
                            f"💡 Please refresh the page and try again with available assets."
                        )

                    old_location = asset.current_location.name
                    asset.write({
                        'current_location': move.destination_location.id,
                        'source_location': move.source_location.id or False,
                        'last_move_date': fields.Datetime.now(),
                    })
                    move.message_post(
                        body=f"🔄 Asset transferred: {asset.serial_number} from {old_location} to {move.destination_location.name}"
                    )

                _logger.info(f"✅ Transferred {len(move.selected_asset_ids)} assets in move {move.reference}")

            # ================================================================
            # === SCRAP: Mark assets as scrapped ===
            # ================================================================
            if move.move_type == 'scrap' and move.product_id.product_type == 'asset':
                _logger.info("📌 ASSET SCRAP: Processing asset scrap")

                if not move.selected_asset_ids:
                    raise ValidationError('Please select at least one asset to scrap!')

                # Check if selected assets are in different locations
                selected_locations = move.selected_asset_ids.mapped('current_location')
                if len(selected_locations) > 1:
                    move.message_post(
                        body=f"⚠️ Selected assets are in different locations: {', '.join(selected_locations.mapped('name'))}."
                    )

                for asset in move.selected_asset_ids:
                    if asset.status != 'available':
                        raise ValidationError(
                            f"❌ Asset Not Available\n\n"
                            f"Asset {asset.serial_number} is no longer available.\n"
                            f"Current status: {asset.status}\n\n"
                            f"💡 Please refresh the page and try again with available assets."
                        )

                    asset.write({
                        'status': 'scrapped',
                        'current_location': False,
                        'source_location': move.source_location.id or False,
                        'last_move_date': fields.Datetime.now(),
                    })
                    move.message_post(body=f"🗑️ Asset scrapped: {asset.serial_number}")

                _logger.info(f"✅ Scrapped {len(move.selected_asset_ids)} assets in move {move.reference}")

            # === UPDATE INVENTORY ===
            _logger.info(f"🔴🔴🔴 Calling _update_inventory for move: {move.id}")
            _logger.info(f"  Move Type: {move.move_type}")
            _logger.info(f"  Product Type: {move.product_type}")

            self._update_inventory(move)

            _logger.info(f"🔴🔴🔴 _update_inventory RETURNED for move: {move.id}")

            if move.reference == 'New':
                seq_code = move._get_sequence_code()
                move.reference = self.env['ir.sequence'].next_by_code(seq_code) or 'New'

            move.state = 'confirmed'
            move.message_post(body=f"✅ {move.move_type.title()} confirmed: {move.quantity} {move.product_id.name}")

            _logger.info(f"✅ MOVE CONFIRMED: {move.reference} - {move.move_type}")

        _logger.info("=" * 60)
        _logger.info("🔴🔴🔴 action_confirm COMPLETED 🔴🔴🔴")
        _logger.info("=" * 60)

    def action_cancel(self):
        """Cancel the stock move"""
        for move in self:
            if move.state == 'draft':
                move.state = 'cancelled'
                move.message_post(body=f"❌ Stock move {move.reference} cancelled")
            else:
                raise ValidationError(
                    f"❌ Cannot cancel a {move.state} move.\n\n"
                    f"Only draft moves can be cancelled."
                )

    def _update_inventory(self, move):
        _logger.info("=" * 60)
        _logger.info(f"🔴🔴🔴 _update_inventory CALLED for move: {move.id}")
        _logger.info(f"  Product: {move.product_id.name if move.product_id else 'None'}")
        _logger.info(f"  Product Type: {move.product_type}")
        _logger.info(f"  Move Type: {move.move_type}")
        _logger.info(f"  Quantity: {move.quantity}")
        _logger.info(f"  Source Location: {move.source_location.name if move.source_location else 'None'}")
        _logger.info(
            f"  Destination Location: {move.destination_location.name if move.destination_location else 'None'}")
        _logger.info(f"  State: {move.state}")
        _logger.info("=" * 60)

        Inventory = self.env['una.inventory'].sudo()

        # ================================================================
        # === ASSET PRODUCTS: Update inventory ===
        # ================================================================
        if move.product_id.product_type == 'asset':
            _logger.info("📌 ASSET: Updating asset inventory")

            # Find or create inventory record for this product at the relevant location
            if move.move_type == 'receipt':
                _logger.info("📌 ASSET RECEIPT: Creating assets at destination")

                # Receipt: Assets created at destination
                inv = Inventory.search([
                    ('product_id', '=', move.product_id.id),
                    ('location_id', '=', move.destination_location.id)
                ])
                # Count actual assets at this location
                available_count = self.env['una.asset'].search_count([
                    ('product_id', '=', move.product_id.id),
                    ('current_location', '=', move.destination_location.id),
                    ('status', '=', 'available')
                ])
                assigned_count = self.env['una.asset'].search_count([
                    ('product_id', '=', move.product_id.id),
                    ('current_location', '=', move.destination_location.id),
                    ('status', '=', 'assigned')
                ])

                _logger.info(f"  Available count: {available_count}")
                _logger.info(f"  Assigned count: {assigned_count}")

                if inv:
                    inv.quantity_on_hand = available_count
                    inv.reserved_quantity = assigned_count
                    _logger.info(
                        f"  Updated existing inventory: {inv.quantity_on_hand} units, Reserved: {inv.reserved_quantity}")
                else:
                    Inventory.create({
                        'product_id': move.product_id.id,
                        'location_id': move.destination_location.id,
                        'quantity_on_hand': available_count,
                        'reserved_quantity': assigned_count,
                    })
                    _logger.info(
                        f"  ✅ Created NEW asset inventory: {available_count} units at {move.destination_location.name}, Reserved: {assigned_count}")

            elif move.move_type == 'issue':
                _logger.info("📌 ASSET ISSUE: Updating asset issue inventory")

                if move.source_location:
                    source_inv = Inventory.search([
                        ('product_id', '=', move.product_id.id),
                        ('location_id', '=', move.source_location.id)
                    ])
                    if source_inv:
                        available_count = self.env['una.asset'].search_count([
                            ('product_id', '=', move.product_id.id),
                            ('current_location', '=', move.source_location.id),
                            ('status', '=', 'available')
                        ])
                        assigned_count = self.env['una.asset'].search_count([
                            ('product_id', '=', move.product_id.id),
                            ('current_location', '=', move.source_location.id),
                            ('status', '=', 'assigned')
                        ])
                        source_inv.quantity_on_hand = available_count
                        source_inv.reserved_quantity = assigned_count
                        _logger.info(
                            f"  Updated source inventory: {available_count} available, {assigned_count} assigned")

                # Update destination location
                if move.destination_location:
                    dest_inv = Inventory.search([
                        ('product_id', '=', move.product_id.id),
                        ('location_id', '=', move.destination_location.id)
                    ])
                    available_count = self.env['una.asset'].search_count([
                        ('product_id', '=', move.product_id.id),
                        ('current_location', '=', move.destination_location.id),
                        ('status', '=', 'available')
                    ])
                    assigned_count = self.env['una.asset'].search_count([
                        ('product_id', '=', move.product_id.id),
                        ('current_location', '=', move.destination_location.id),
                        ('status', '=', 'assigned')
                    ])

                    if dest_inv:
                        dest_inv.quantity_on_hand = available_count
                        dest_inv.reserved_quantity = assigned_count
                        _logger.info(
                            f"  Updated destination inventory: {available_count} available, {assigned_count} assigned")
                    else:
                        Inventory.create({
                            'product_id': move.product_id.id,
                            'location_id': move.destination_location.id,
                            'quantity_on_hand': available_count,
                            'reserved_quantity': assigned_count,
                        })
                        _logger.info(
                            f"  ✅ Created destination inventory: {available_count} available, {assigned_count} assigned")

            elif move.move_type == 'transfer':
                _logger.info("📌 ASSET TRANSFER: Updating asset transfer inventory")

                if move.source_location:
                    source_inv = Inventory.search([
                        ('product_id', '=', move.product_id.id),
                        ('location_id', '=', move.source_location.id)
                    ])
                    if source_inv:
                        available_count = self.env['una.asset'].search_count([
                            ('product_id', '=', move.product_id.id),
                            ('current_location', '=', move.source_location.id),
                            ('status', '=', 'available')
                        ])
                        assigned_count = self.env['una.asset'].search_count([
                            ('product_id', '=', move.product_id.id),
                            ('current_location', '=', move.source_location.id),
                            ('status', '=', 'assigned')
                        ])
                        source_inv.quantity_on_hand = available_count
                        source_inv.reserved_quantity = assigned_count
                        _logger.info(
                            f"  Updated source inventory: {available_count} available, {assigned_count} assigned")

                # Update destination location
                if move.destination_location:
                    dest_inv = Inventory.search([
                        ('product_id', '=', move.product_id.id),
                        ('location_id', '=', move.destination_location.id)
                    ])
                    available_count = self.env['una.asset'].search_count([
                        ('product_id', '=', move.product_id.id),
                        ('current_location', '=', move.destination_location.id),
                        ('status', '=', 'available')
                    ])
                    assigned_count = self.env['una.asset'].search_count([
                        ('product_id', '=', move.product_id.id),
                        ('current_location', '=', move.destination_location.id),
                        ('status', '=', 'assigned')
                    ])

                    if dest_inv:
                        dest_inv.quantity_on_hand = available_count
                        dest_inv.reserved_quantity = assigned_count
                        _logger.info(
                            f"  Updated destination inventory: {available_count} available, {assigned_count} assigned")
                    else:
                        Inventory.create({
                            'product_id': move.product_id.id,
                            'location_id': move.destination_location.id,
                            'quantity_on_hand': available_count,
                            'reserved_quantity': assigned_count,
                        })
                        _logger.info(
                            f"  ✅ Created destination inventory: {available_count} available, {assigned_count} assigned")

            elif move.move_type == 'scrap':
                # Scrap: Asset removed from location
                _logger.info("📌 ASSET SCRAP: Updating asset scrap inventory")

                if move.source_location:
                    inv = Inventory.search([
                        ('product_id', '=', move.product_id.id),
                        ('location_id', '=', move.source_location.id)
                    ])
                    if inv:
                        available_count = self.env['una.asset'].search_count([
                            ('product_id', '=', move.product_id.id),
                            ('current_location', '=', move.source_location.id),
                            ('status', '=', 'available')
                        ])
                        assigned_count = self.env['una.asset'].search_count([
                            ('product_id', '=', move.product_id.id),
                            ('current_location', '=', move.source_location.id),
                            ('status', '=', 'assigned')
                        ])
                        inv.quantity_on_hand = available_count
                        inv.reserved_quantity = assigned_count
                        _logger.info(f"  Updated inventory: {available_count} available, {assigned_count} assigned")

            _logger.info("✅ ASSET inventory update complete")
            return  # Skip the rest of the method for assets

        # ================================================================
        # === CONSUMABLE PRODUCTS: Update inventory ===
        # ================================================================
        _logger.info("📌 CONSUMABLE: Updating consumable inventory")

        # ✅ Skip if quantity is 0 or negative
        if move.quantity <= 0:
            _logger.info("⚠️ Quantity <= 0, skipping inventory update")
            return

        # --- RECEIPT: Add stock at destination ---
        if move.move_type == 'receipt':
            _logger.info(f"📥 CONSUMABLE RECEIPT: Adding stock at destination")
            _logger.info(f"  Destination: {move.destination_location.name if move.destination_location else 'None'}")

            inv = Inventory.search([
                ('product_id', '=', move.product_id.id),
                ('location_id', '=', move.destination_location.id)
            ])

            _logger.info(f"  Existing inventory found: {inv.quantity_on_hand if inv else 'None'}")

            if inv:
                inv.quantity_on_hand += move.quantity
                # reserved_quantity stays the same for receipts
                _logger.info(f"  Updated inventory: {inv.quantity_on_hand} units, Reserved: {inv.reserved_quantity}")
            else:
                Inventory.create({
                    'product_id': move.product_id.id,
                    'location_id': move.destination_location.id,
                    'quantity_on_hand': move.quantity,
                    'reserved_quantity': 0,  # New inventory starts with 0 reserved
                })
                _logger.info(
                    f"  ✅ Created NEW consumable inventory: {move.quantity} units at {move.destination_location.name}")

            move.message_post(
                body=f"📥 Received {move.quantity} {move.product_id.name} at {move.destination_location.name}"
            )
            _logger.info("✅ CONSUMABLE RECEIPT inventory update complete")
            return

        # --- ISSUE: Remove from source, ADD to destination ---
        elif move.move_type == 'issue':
            _logger.info(f"📤 CONSUMABLE ISSUE: Removing from source, adding to destination")
            _logger.info(f"  Source: {move.source_location.name if move.source_location else 'None'}")
            _logger.info(f"  Destination: {move.destination_location.name if move.destination_location else 'None'}")

            # 1. Remove from source location
            source_inv = Inventory.search([
                ('product_id', '=', move.product_id.id),
                ('location_id', '=', move.source_location.id)
            ])
            if source_inv:
                if source_inv.quantity_on_hand < move.quantity:
                    raise ValidationError(
                        f'Insufficient stock at {move.source_location.name}! '
                        f'Available: {source_inv.quantity_on_hand}, Requested: {move.quantity}'
                    )
                source_inv.quantity_on_hand -= move.quantity
                # Decrease reserved_quantity at source (stock is no longer reserved)
                if source_inv.reserved_quantity >= move.quantity:
                    source_inv.reserved_quantity -= move.quantity
                else:
                    source_inv.reserved_quantity = 0
                _logger.info(
                    f"  Removed from source: {source_inv.quantity_on_hand} units remaining, Reserved: {source_inv.reserved_quantity}")
                move.message_post(
                    body=f"📍 Removed {move.quantity} {move.product_id.name} from {move.source_location.name}"
                )
            else:
                raise ValidationError(f'No inventory found at {move.source_location.name}!')

            # 2. ADD to destination location (if it exists)
            if move.destination_location:
                dest_inv = Inventory.search([
                    ('product_id', '=', move.product_id.id),
                    ('location_id', '=', move.destination_location.id)
                ])
                if dest_inv:
                    dest_inv.quantity_on_hand += move.quantity
                    # Increase reserved_quantity at destination (stock is now reserved here)
                    dest_inv.reserved_quantity += move.quantity
                    _logger.info(
                        f"  Added to destination: {dest_inv.quantity_on_hand} units total, Reserved: {dest_inv.reserved_quantity}")
                else:
                    dest_inv = Inventory.create({
                        'product_id': move.product_id.id,
                        'location_id': move.destination_location.id,
                        'quantity_on_hand': move.quantity,
                        'reserved_quantity': move.quantity,  # New inventory with reserved stock
                    })
                    _logger.info(f"  ✅ Created destination inventory: {move.quantity} units, Reserved: {move.quantity}")
                move.message_post(
                    body=f"📍 Added {move.quantity} {move.product_id.name} to {move.destination_location.name}"
                )
            _logger.info("✅ CONSUMABLE ISSUE inventory update complete")
            return

        elif move.move_type == 'transfer':
            _logger.info(f"🔄 CONSUMABLE TRANSFER: Removing from source, adding to destination")
            _logger.info(f"  Source: {move.source_location.name if move.source_location else 'None'}")
            _logger.info(f"  Destination: {move.destination_location.name if move.destination_location else 'None'}")

            source_inv = Inventory.search([
                ('product_id', '=', move.product_id.id),
                ('location_id', '=', move.source_location.id)
            ])
            if source_inv:
                if source_inv.quantity_on_hand < move.quantity:
                    raise ValidationError(
                        f'Insufficient stock at {move.source_location.name}! '
                        f'Available: {source_inv.quantity_on_hand}, Requested: {move.quantity}'
                    )
                source_inv.quantity_on_hand -= move.quantity
                # Decrease reserved_quantity at source
                if source_inv.reserved_quantity >= move.quantity:
                    source_inv.reserved_quantity -= move.quantity
                else:
                    source_inv.reserved_quantity = 0
                _logger.info(
                    f"  Removed from source: {source_inv.quantity_on_hand} units remaining, Reserved: {source_inv.reserved_quantity}")
                move.message_post(
                    body=f"📍 Removed {move.quantity} {move.product_id.name} from {move.source_location.name}"
                )
            else:
                raise ValidationError(f'No inventory found at source location!')

            dest_inv = Inventory.search([
                ('product_id', '=', move.product_id.id),
                ('location_id', '=', move.destination_location.id)
            ])
            if dest_inv:
                dest_inv.quantity_on_hand += move.quantity
                # Increase reserved_quantity at destination
                dest_inv.reserved_quantity += move.quantity
                _logger.info(
                    f"  Added to destination: {dest_inv.quantity_on_hand} units total, Reserved: {dest_inv.reserved_quantity}")
            else:
                dest_inv = Inventory.create({
                    'product_id': move.product_id.id,
                    'location_id': move.destination_location.id,
                    'quantity_on_hand': move.quantity,
                    'reserved_quantity': move.quantity,  # New inventory with reserved stock
                })
                _logger.info(f"  ✅ Created destination inventory: {move.quantity} units, Reserved: {move.quantity}")
            move.message_post(
                body=f"📍 Added {move.quantity} {move.product_id.name} to {move.destination_location.name}"
            )
            _logger.info("✅ CONSUMABLE TRANSFER inventory update complete")
            return

        # --- SCRAP: Remove from source only ---
        elif move.move_type == 'scrap':
            _logger.info(f"🗑️ CONSUMABLE SCRAP: Removing from source only")
            _logger.info(f"  Source: {move.source_location.name if move.source_location else 'None'}")

            inv = Inventory.search([
                ('product_id', '=', move.product_id.id),
                ('location_id', '=', move.source_location.id)
            ])
            if inv:
                if inv.quantity_on_hand < move.quantity:
                    raise ValidationError(
                        f'Insufficient stock at {move.source_location.name}! '
                        f'Available: {inv.quantity_on_hand}, Requested: {move.quantity}'
                    )
                inv.quantity_on_hand -= move.quantity
                # Decrease reserved_quantity at source (scrapped items are no longer reserved)
                if inv.reserved_quantity >= move.quantity:
                    inv.reserved_quantity -= move.quantity
                else:
                    inv.reserved_quantity = 0
                _logger.info(
                    f"  Removed from source: {inv.quantity_on_hand} units remaining, Reserved: {inv.reserved_quantity}")
                move.message_post(
                    body=f"🗑️ Scrapped {move.quantity} {move.product_id.name} from {move.source_location.name}"
                )
            else:
                raise ValidationError(f'No inventory found at {move.source_location.name}!')
            _logger.info("✅ CONSUMABLE SCRAP inventory update complete")
            return

        # --- ADJUSTMENT: Add to destination ---
        elif move.move_type == 'adjustment':
            _logger.info(f"📝 CONSUMABLE ADJUSTMENT: Adding to destination")
            _logger.info(f"  Destination: {move.destination_location.name if move.destination_location else 'None'}")

            inv = Inventory.search([
                ('product_id', '=', move.product_id.id),
                ('location_id', '=', move.destination_location.id)
            ])
            if inv:
                inv.quantity_on_hand += move.quantity
                # reserved_quantity stays the same for adjustments
                _logger.info(f"  Updated inventory: {inv.quantity_on_hand} units, Reserved: {inv.reserved_quantity}")
            else:
                Inventory.create({
                    'product_id': move.product_id.id,
                    'location_id': move.destination_location.id,
                    'quantity_on_hand': move.quantity,
                    'reserved_quantity': 0,  # New inventory starts with 0 reserved
                })
                _logger.info(f"  ✅ Created inventory: {move.quantity} units")
            move.message_post(
                body=f"📝 Adjusted {move.quantity} {move.product_id.name} at {move.destination_location.name}"
            )
            _logger.info("✅ CONSUMABLE ADJUSTMENT inventory update complete")
            return

        _logger.info("=" * 60)
        _logger.info(f"✅ _update_inventory COMPLETED for move: {move.id}")
        _logger.info("=" * 60)