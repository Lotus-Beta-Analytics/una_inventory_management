from odoo import models, fields, api
from odoo.exceptions import ValidationError
import re


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
        compute='_compute_is_serial_tracked'
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
            if move.state == 'draft' and move.move_type in ['issue', 'transfer', 'scrap'] and move.product_id.product_type == 'asset' and move.selected_asset_ids:
                # Get the first asset's location for display
                asset = move.selected_asset_ids[0]
                move.auto_source_location = asset.current_location.name if asset.current_location else 'No location set'
            elif move.state == 'confirmed' and move.auto_source_location:
                pass
            else:
                move.auto_source_location = False

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

    def action_confirm(self):
        for move in self:
            # ================================================================
            # === CONSUMABLE: Auto-set source from inventory ===
            # ================================================================
            if move.move_type in ['issue', 'transfer', 'scrap'] and move.product_type == 'consumable':
                inventory = self.env['una.inventory'].search([
                    ('product_id', '=', move.product_id.id),
                    ('location_id', '=', move.source_location.id)
                ], order='quantity_on_hand desc', limit=1)

                if inventory:
                    move.source_location = inventory.location_id.id
                    move.message_post(
                        body=f"📍 Source location auto-set to: {inventory.location_id.name} (from inventory)"
                    )
                else:
                    raise ValidationError(
                        f'No inventory found for {move.product_id.name}! '
                        'Please receive stock first.'
                    )

            # ================================================================
            # === ASSET: Validation and auto-set ===
            # ================================================================
            if move.move_type in ['issue', 'transfer', 'scrap'] and move.product_id.product_type == 'asset':
                if not move.selected_asset_ids:
                    raise ValidationError(f'Please select at least one asset to {move.move_type}!')

                # Auto-set quantity based on number of selected assets
                move.quantity = len(move.selected_asset_ids)

                # Check all assets have a location
                for asset in move.selected_asset_ids:
                    if not asset.current_location:
                        raise ValidationError(f"Asset {asset.serial_number} has no current location!")

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

            # === YOUR EXISTING CODE CONTINUES ===
            if move.state != 'draft':
                raise ValidationError('Only draft moves can be confirmed!')

            if move.cost_price_at_move <= 0:
                raise ValidationError('Cost must be greater than zero!')

            # ================================================================
            # === RECEIPT: Auto-create assets ===
            # ================================================================
            if move.move_type == 'receipt' and move.is_serial_tracked:
                final_serials = []

                if move.serial_entry_method == 'single':
                    if move.serial_numbers:
                        final_serials = [s.strip() for s in move.serial_numbers.split('\n') if s.strip()]
                    if not final_serials:
                        raise ValidationError('Please enter serial numbers!')

                elif move.serial_entry_method == 'range':
                    if not move.first_serial_number:
                        raise ValidationError('Please enter first serial number!')
                    final_serials = move._generate_serial_range(move.first_serial_number, int(move.quantity))

                if len(final_serials) != int(move.quantity):
                    raise ValidationError(
                        f'Number of serials ({len(final_serials)}) does not match quantity ({int(move.quantity)})!')

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

            # ================================================================
            # === ISSUE: Assign assets (FIXED - Preserves manual selection) ===
            # ================================================================
            if move.move_type == 'issue' and move.product_id.product_type == 'asset':
                # ★ Check if user manually selected assets
                user_selected = bool(move.selected_asset_ids)

                if not user_selected:
                    # Only auto-select if user hasn't selected anything
                    available_assets = self.env['una.asset'].search([
                        ('product_id', '=', move.product_id.id),
                        ('status', '=', 'available')
                    ])

                    if not available_assets:
                        raise ValidationError(f'No available assets for {move.product_id.name}!')

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
                        raise ValidationError(f"Asset {asset.serial_number} is no longer available!")

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

            # ================================================================
            # === TRANSFER: Move assets ===
            # ================================================================
            if move.move_type == 'transfer' and move.product_id.product_type == 'asset':
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
                        raise ValidationError(f"Asset {asset.serial_number} is no longer available!")

                    old_location = asset.current_location.name
                    asset.write({
                        'current_location': move.destination_location.id,
                        'source_location': move.source_location.id or False,
                        'last_move_date': fields.Datetime.now(),
                    })
                    move.message_post(
                        body=f"🔄 Asset transferred: {asset.serial_number} from {old_location} to {move.destination_location.name}"
                    )

            # ================================================================
            # === SCRAP: Mark assets as scrapped ===
            # ================================================================
            if move.move_type == 'scrap' and move.product_id.product_type == 'asset':
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
                        raise ValidationError(f"Asset {asset.serial_number} is no longer available!")

                    asset.write({
                        'status': 'scrapped',
                        'current_location': False,
                        'source_location': move.source_location.id or False,
                        'last_move_date': fields.Datetime.now(),
                    })
                    move.message_post(body=f"🗑️ Asset scrapped: {asset.serial_number}")

            # === UPDATE INVENTORY ===
            self._update_inventory(move)

            move.state = 'confirmed'
            move.message_post(body=f"✅ {move.move_type.title()} confirmed: {move.quantity} {move.product_id.name}")

    # USE THIS FOR NORMAL CASE NO EDGE CASE
    # def action_confirm(self):
    #     for move in self:
    #
    #         if move.move_type in ['issue', 'transfer', 'scrap'] and move.product_type == 'consumable':
    #             inventory = self.env['una.inventory'].search([
    #                 ('product_id', '=', move.product_id.id),
    #                 ('location_id', '=', move.source_location.id)
    #             ], order='quantity_on_hand desc', limit=1)
    #
    #             if inventory:
    #                 move.source_location = inventory.location_id.id
    #                 move.message_post(
    #                     body=f"📍 Source location auto-set to: {inventory.location_id.name} (from inventory)"
    #                 )
    #             else:
    #                 raise ValidationError(
    #                     f'No inventory found for {move.product_id.name}! '
    #                     'Please receive stock first.'
    #                 )
    #
    #         if move.move_type in ['issue', 'transfer', 'scrap'] and move.product_id.product_type == 'asset':
    #             if not move.selected_asset_ids:
    #                 raise ValidationError(f'Please select at least one asset to {move.move_type}!')
    #
    #             # Auto-set quantity based on number of selected assets
    #             move.quantity = len(move.selected_asset_ids)
    #
    #             # Check all assets have a location
    #             for asset in move.selected_asset_ids:
    #                 if not asset.current_location:
    #                     raise ValidationError(f"Asset {asset.serial_number} has no current location!")
    #
    #             # Auto-set source location from the first asset
    #             first_asset = move.selected_asset_ids[0]
    #             move.auto_source_location = first_asset.current_location.name
    #             move.source_location = first_asset.current_location.id
    #             move.message_post(
    #                 body=f"📍 Moving From auto-set to: {first_asset.current_location.name} from {len(move.selected_asset_ids)} asset(s)"
    #             )
    #
    #         # === YOUR EXISTING CODE CONTINUES ===
    #         if move.state != 'draft':
    #             raise ValidationError('Only draft moves can be confirmed!')
    #
    #         if move.cost_price_at_move <= 0:
    #             raise ValidationError('Cost must be greater than zero!')
    #
    #         # ================================================================
    #         # === RECEIPT: Auto-create assets ===
    #         # ================================================================
    #         if move.move_type == 'receipt' and move.is_serial_tracked:
    #             final_serials = []
    #
    #             if move.serial_entry_method == 'single':
    #                 if move.serial_numbers:
    #                     final_serials = [s.strip() for s in move.serial_numbers.split('\n') if s.strip()]
    #                 if not final_serials:
    #                     raise ValidationError('Please enter serial numbers!')
    #
    #             elif move.serial_entry_method == 'range':
    #                 if not move.first_serial_number:
    #                     raise ValidationError('Please enter first serial number!')
    #                 final_serials = move._generate_serial_range(move.first_serial_number, int(move.quantity))
    #
    #             if len(final_serials) != int(move.quantity):
    #                 raise ValidationError(
    #                     f'Number of serials ({len(final_serials)}) does not match quantity ({int(move.quantity)})!')
    #
    #             cost_per_asset = move.cost_price_at_move / len(final_serials)
    #             for serial in final_serials:
    #                 self.env['una.asset'].create({
    #                     'name': f"{move.product_id.name} - {serial}",
    #                     'product_id': move.product_id.id,
    #                     'serial_number': serial,
    #                     'cost_price': cost_per_asset,
    #                     'current_location': move.destination_location.id,
    #                     'source_location': move.source_location.id or False,
    #                     'last_move_date': fields.Datetime.now(),
    #                     'status': 'available',
    #                     'purchase_date': fields.Date.today(),
    #                     'stock_move_id': move.id,
    #                 })
    #                 move.message_post(body=f"📥 Asset created: {serial}")
    #
    #         # ================================================================
    #         # === ISSUE: Assign assets (FIXED - No activity on asset) ===
    #         # ================================================================
    #         if move.move_type == 'issue' and move.product_id.product_type == 'asset':
    #             if not move.selected_asset_ids:
    #                 available_assets = self.env['una.asset'].search([
    #                     ('product_id', '=', move.product_id.id),
    #                     ('status', '=', 'available')
    #                 ], limit=1)
    #
    #                 if not available_assets:
    #                     raise ValidationError(f'No available assets for {move.product_id.name}!')
    #
    #                 move.selected_asset_ids = [(6, 0, available_assets.ids)]
    #                 move.quantity = len(move.selected_asset_ids)
    #                 move.message_post(body=f"🤖 Auto-selected asset(s) for issue")
    #             else:
    #                 move.message_post(body=f"📝 Admin manually selected asset(s) for issue")
    #
    #             # Get employee from stock move
    #             employee_id = move.employee_id.id if move.employee_id else False
    #             employee = move.employee_id
    #
    #             for asset in move.selected_asset_ids:
    #                 if asset.status != 'available':
    #                     raise ValidationError(f"Asset {asset.serial_number} is no longer available!")
    #
    #                 asset.write({
    #                     'status': 'assigned',
    #                     'assigned_date': fields.Date.today(),
    #                     'current_location': move.destination_location.id or asset.current_location.id,
    #                     'source_location': move.source_location.id or False,
    #                     'last_move_date': fields.Datetime.now(),
    #                     'assigned_to': employee_id,
    #                 })
    #
    #                 # Update inventory reserved quantity
    #                 inventory = self.env['una.inventory'].search([
    #                     ('product_id', '=', move.product_id.id),
    #                     ('location_id', '=', move.source_location.id)
    #                 ])
    #                 if inventory:
    #                     inventory.reserved_quantity += 1
    #
    #                 employee_name = employee.name if employee else 'N/A'
    #                 move.message_post(body=f"✅ Asset assigned: {asset.serial_number} to {employee_name}")
    #
    #                 # ★ FIXED: Send email to employee (no activity on asset)
    #                 if employee and (employee.work_email or employee.user_id.email):
    #                     template = self.env.ref('una_inventory_management.email_template_asset_assignment',
    #                                             raise_if_not_found=False)
    #                     if template:
    #                         try:
    #                             # Use move.id as the template's model ID
    #                             template.send_mail(move.id, force_send=True, raise_exception=False,
    #                                                email_values={
    #                                                    'email_to': employee.work_email or employee.user_id.email
    #                                                })
    #                         except Exception as e:
    #                             move.message_post(body=f"⚠️ Email could not be sent: {str(e)}")
    #
    #         # ================================================================
    #         # === TRANSFER: Move assets ===
    #         # ================================================================
    #         if move.move_type == 'transfer' and move.product_id.product_type == 'asset':
    #             if not move.selected_asset_ids:
    #                 raise ValidationError('Please select at least one asset to transfer!')
    #
    #             for asset in move.selected_asset_ids:
    #                 if asset.status != 'available':
    #                     raise ValidationError(f"Asset {asset.serial_number} is no longer available!")
    #
    #                 old_location = asset.current_location.name
    #                 asset.write({
    #                     'current_location': move.destination_location.id,
    #                     'source_location': move.source_location.id or False,
    #                     'last_move_date': fields.Datetime.now(),
    #                 })
    #                 move.message_post(
    #                     body=f"🔄 Asset transferred: {asset.serial_number} from {old_location} to {move.destination_location.name}"
    #                 )
    #
    #         # ================================================================
    #         # === SCRAP: Mark assets as scrapped ===
    #         # ================================================================
    #         if move.move_type == 'scrap' and move.product_id.product_type == 'asset':
    #             if not move.selected_asset_ids:
    #                 raise ValidationError('Please select at least one asset to scrap!')
    #
    #             for asset in move.selected_asset_ids:
    #                 if asset.status != 'available':
    #                     raise ValidationError(f"Asset {asset.serial_number} is no longer available!")
    #
    #                 asset.write({
    #                     'status': 'scrapped',
    #                     'current_location': False,
    #                     'source_location': move.source_location.id or False,
    #                     'last_move_date': fields.Datetime.now(),
    #                 })
    #                 move.message_post(body=f"🗑️ Asset scrapped: {asset.serial_number}")
    #
    #         self._update_inventory(move)
    #
    #         move.state = 'confirmed'
    #         move.message_post(body=f"✅ {move.move_type.title()} confirmed: {move.quantity} {move.product_id.name}")


    def _update_inventory(self, move):
        Inventory = self.env['una.inventory'].sudo()

        if move.product_id.product_type == 'asset':
            # Find or create inventory record for this product at the relevant location
            if move.move_type == 'receipt':
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

                if inv:
                    inv.quantity_on_hand = available_count
                    inv.reserved_quantity = assigned_count
                else:
                    Inventory.create({
                        'product_id': move.product_id.id,
                        'location_id': move.destination_location.id,
                        'quantity_on_hand': available_count,
                        'reserved_quantity': assigned_count,
                    })

            elif move.move_type == 'issue':
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
                    else:
                        Inventory.create({
                            'product_id': move.product_id.id,
                            'location_id': move.destination_location.id,
                            'quantity_on_hand': available_count,
                            'reserved_quantity': assigned_count,
                        })

            elif move.move_type == 'transfer':
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
                    else:
                        Inventory.create({
                            'product_id': move.product_id.id,
                            'location_id': move.destination_location.id,
                            'quantity_on_hand': available_count,
                            'reserved_quantity': assigned_count,
                        })

            elif move.move_type == 'scrap':
                # Scrap: Asset removed from location
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

            return  # Skip the rest of the method for assets

        # ================================================================
        # === CONSUMABLE PRODUCTS: Update inventory normally ===
        # ================================================================
        if move.move_type == 'receipt':
            inv = Inventory.search([
                ('product_id', '=', move.product_id.id),
                ('location_id', '=', move.destination_location.id)
            ])
            if inv:
                inv.quantity_on_hand += move.quantity
            else:
                Inventory.create({
                    'product_id': move.product_id.id,
                    'location_id': move.destination_location.id,
                    'quantity_on_hand': move.quantity
                })

        elif move.move_type == 'issue':
            inv = Inventory.search([
                ('product_id', '=', move.product_id.id),
                ('location_id', '=', move.source_location.id)
            ])
            if inv:
                if inv.quantity_on_hand < move.quantity:
                    raise ValidationError(f'Insufficient stock! Available: {inv.quantity_on_hand}')
                inv.quantity_on_hand -= move.quantity

        elif move.move_type == 'transfer':
            source_inv = Inventory.search([
                ('product_id', '=', move.product_id.id),
                ('location_id', '=', move.source_location.id)
            ])
            if source_inv:
                if source_inv.quantity_on_hand < move.quantity:
                    raise ValidationError(f'Insufficient stock at source!')
                source_inv.quantity_on_hand -= move.quantity

            dest_inv = Inventory.search([
                ('product_id', '=', move.product_id.id),
                ('location_id', '=', move.destination_location.id)
            ])
            if dest_inv:
                dest_inv.quantity_on_hand += move.quantity
            else:
                Inventory.create({
                    'product_id': move.product_id.id,
                    'location_id': move.destination_location.id,
                    'quantity_on_hand': move.quantity
                })

        elif move.move_type == 'scrap':
            inv = Inventory.search([
                ('product_id', '=', move.product_id.id),
                ('location_id', '=', move.source_location.id)
            ])
            if inv:
                if inv.quantity_on_hand < move.quantity:
                    raise ValidationError(f'Insufficient stock! Available: {inv.quantity_on_hand}')
                inv.quantity_on_hand -= move.quantity

        elif move.move_type == 'adjustment':
            inv = Inventory.search([
                ('product_id', '=', move.product_id.id),
                ('location_id', '=', move.destination_location.id)
            ])
            if inv:
                inv.quantity_on_hand += move.quantity
            else:
                Inventory.create({
                    'product_id': move.product_id.id,
                    'location_id': move.destination_location.id,
                    'quantity_on_hand': move.quantity
                })