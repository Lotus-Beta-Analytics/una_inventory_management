from odoo import models, fields, api
from odoo.exceptions import UserError
from datetime import timedelta


class UnaRequisition(models.Model):
    _name = 'una.requisition'
    _description = 'UNA Requisition'
    _rec_name = 'name'
    _order = 'create_date desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Reference', readonly=True, default='New')

    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        required=True,
        default=lambda self: self.env.user.employee_id
    )

    department_id = fields.Many2one(
        'hr.department',
        string='Department',
        related='employee_id.department_id',
        store=True
    )

    station_id = fields.Many2one(
        'hr.employee.station',
        string='Station',
        related='employee_id.station_id',
        store=True,
        help="Employee's station"
    )

    product_id = fields.Many2one('una.product', string='Product', required=True)
    quantity = fields.Float(string='Quantity', required=True, default=1.0)

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

    is_bundle_requisition = fields.Boolean(
        string='Is Bundle',
        compute='_compute_bundle_fields',
        store=False,
    )

    quantity_in_bundles = fields.Float(
        string='Bundles',
        compute='_compute_bundle_fields',
        store=False,
    )

    @api.depends('product_id', 'quantity')
    def _compute_bundle_fields(self):
        for req in self:
            if req.product_id and req.product_id.is_bundle and req.product_id.bundle_quantity > 0:
                req.is_bundle_requisition = True
                req.quantity_in_bundles = req.quantity / req.product_id.bundle_quantity
            else:
                req.is_bundle_requisition = False
                req.quantity_in_bundles = 0.0

    estimated_cost = fields.Monetary(
        string='Estimated Cost',
        currency_field='currency_id',
        required=True,
        default=0.0
    )

    total_cost = fields.Monetary(
        string='Total Cost',
        currency_field='currency_id',
        store=True,
        help="Estimated Cost x Quantity",
        compute='_compute_total_cost'
    )

    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id
    )

    @api.depends('estimated_cost', 'quantity')
    def _compute_total_cost(self):
        for req in self:
            if req:
                req.total_cost = req.estimated_cost * req.quantity
            else:
                req.total_cost = 0.0

    destination_location = fields.Many2one('una.location', string='Destination', required=True)
    purpose = fields.Text(string='Purpose/Reason', required=True)
    required_date = fields.Date(string='Required By')

    # === APPROVAL STATE ===
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('line_manager_approved', 'Approved by Line Manager'),
        ('admin_assistant_approved', 'Approved by Admin Assistant'),
        ('admin_manager_approved', 'Approved by Admin Manager'),
        ('director_approved', 'Approved by Director of Admin'),
        ('audit_approved', 'Approved by Audit'),
        ('rejected', 'Rejected')
    ], string='Status', default='draft', tracking=True)

    # === FRONTEND STATUS DISPLAY (NEW) ===
    status_display = fields.Char(
        string='Status Display',
        compute='_compute_status_display',
        store=False,
        help="Dynamic status for frontend display"
    )

    status_color = fields.Char(
        string='Status Color',
        compute='_compute_status_display',
        store=False,
        help="Dynamic color for frontend display"
    )

    @api.depends('state')
    def _compute_status_display(self):
        """Compute dynamic status display and color for frontend"""
        for req in self:
            if req.state == 'audit_approved':
                req.status_display = 'Approved'
                req.status_color = 'success'  # Green
            else:
                req.status_display = dict(req._fields['state'].selection).get(req.state, req.state)
                # Color mapping for other states
                color_map = {
                    'draft': 'secondary',
                    'submitted': 'warning',
                    'line_manager_approved': 'info',
                    'admin_assistant_approved': 'info',
                    'admin_manager_approved': 'info',
                    'director_approved': 'info',
                    'rejected': 'danger',
                }
                req.status_color = color_map.get(req.state, 'secondary')

    # === APPROVAL TIMESTAMPS ===
    submitted_date = fields.Datetime(string='Submitted Date')
    line_manager_approval_date = fields.Datetime(string='Line Manager Date')
    admin_assistant_approval_date = fields.Datetime(string='Admin Assistant Date')
    admin_manager_approval_date = fields.Datetime(string='Admin Manager Date')
    director_approval_date = fields.Datetime(string='Director of Admin Date')
    audit_approval_date = fields.Datetime(string='Audit Date')

    # === COMMENTS ===
    line_manager_comment = fields.Text(string='Line Manager Comment')
    admin_assistant_comment = fields.Text(string='Admin Assistant Comment')
    admin_manager_comment = fields.Text(string='Admin Manager Comment')
    director_comment = fields.Text(string='Director Comment')
    audit_comment = fields.Text(string='Audit Comment')
    rejection_reason = fields.Text(string='Rejection Reason')

    # === ESCALATION ===
    escalation_count = fields.Integer(string='Escalation Count', default=0)
    last_escalation_date = fields.Datetime(string='Last Escalation Date')

    # === STOCK MOVE LINK ===
    stock_move_id = fields.Many2one('una.stock.move', string='Stock Move')

    # === SEQUENCE ===
    @api.model
    def create(self, vals):
        if vals.get('name', 'New') == 'New':
            vals['name'] = self.env['ir.sequence'].next_by_code('una.requisition') or 'New'
        return super().create(vals)

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            if self.product_id.product_type == 'consumable':
                self.estimated_cost = self.product_id.cost_price or 1.00
            else:
                available_asset = self.env['una.asset'].search([
                    ('product_id', '=', self.product_id.id),
                    ('status', '=', 'available')
                ], limit=1)
                if available_asset and available_asset.cost_price:
                    self.estimated_cost = available_asset.cost_price
                else:
                    self.estimated_cost = self.product_id.cost_price or 1.00

    def _check_stock_availability(self):
        self.ensure_one()

        # Only check for consumables
        if self.product_id.product_type != 'consumable':
            return True

        # Get the Admin Office location
        admin_office = self._get_admin_office_location()

        # Check inventory at Admin Office
        inventory = self.env['una.inventory'].search([
            ('product_id', '=', self.product_id.id),
            ('location_id', '=', admin_office.id)
        ], limit=1)

        # If not found at Admin Office, check destination location
        if not inventory or inventory.quantity_on_hand <= 0:
            if self.destination_location.id != admin_office.id:
                inventory = self.env['una.inventory'].search([
                    ('product_id', '=', self.product_id.id),
                    ('location_id', '=', self.destination_location.id)
                ], limit=1)

        # If still not found, check any location
        if not inventory or inventory.quantity_on_hand <= 0:
            inventory = self.env['una.inventory'].search([
                ('product_id', '=', self.product_id.id)
            ], order='quantity_on_hand desc', limit=1)

        if not inventory or inventory.quantity_on_hand <= 0:
            raise UserError(
                f"❌ Product Not Received Yet\n\n"
                f"{self.product_id.name} has not been received into inventory.\n\n"
                f"💡 Please create a RECEIPT for {self.product_id.name} first."
            )

        check_quantity = self.quantity

        if inventory.available_quantity < check_quantity:
            if self.product_id.is_bundle and self.product_id.bundle_quantity > 0:
                available_bundles = inventory.available_quantity / self.product_id.bundle_quantity
                raise UserError(
                    f"❌ Insufficient Available Stock\n\n"
                    f"Requested: {self.quantity} {self.product_id.uom_id.name}\n"
                    f"Available at {inventory.location_id.name}: {inventory.available_quantity} {self.product_id.uom_id.name} ({available_bundles:.1f} {self.product_id.bundle_uom_id.name})\n"
                    f"(On Hand: {inventory.quantity_on_hand}, Reserved: {inventory.reserved_quantity})\n\n"
                    f"💡 Please reduce quantity or receive more stock."
                )
            else:
                raise UserError(
                    f"❌ Insufficient Available Stock\n\n"
                    f"Requested: {self.quantity} {self.product_id.uom_id.name}\n"
                    f"Available at {inventory.location_id.name}: {inventory.available_quantity} {self.product_id.uom_id.name}\n"
                    f"(On Hand: {inventory.quantity_on_hand}, Reserved: {inventory.reserved_quantity})\n\n"
                    f"💡 Please reduce quantity or receive more stock."
                )

        return True

    # === ACTIONS ===
    def action_submit(self):
        for req in self:
            if req.state != 'draft':
                raise UserError('Only draft requisitions can be submitted!')

            req._check_stock_availability()
            req.state = 'submitted'
            req.submitted_date = fields.Datetime.now()
            req._notify_approvers('submitted')

    def action_line_manager_approve(self):
        for req in self:
            if req.state != 'submitted':
                raise UserError('Requisition must be submitted first!')
            req.state = 'line_manager_approved'
            req.line_manager_approval_date = fields.Datetime.now()
            req._notify_approvers('line_manager_approved')

    def action_admin_assistant_approve(self):
        for req in self:
            if req.state != 'line_manager_approved':
                raise UserError('Requisition must be approved by Line Manager first!')
            req.state = 'admin_assistant_approved'
            req.admin_assistant_approval_date = fields.Datetime.now()
            req._notify_approvers('admin_assistant_approved')

    def action_admin_manager_approve(self):
        for req in self:
            if req.state != 'admin_assistant_approved':
                raise UserError('Requisition must be approved by Admin Assistant first!')
            req.state = 'admin_manager_approved'
            req.admin_manager_approval_date = fields.Datetime.now()
            req._notify_approvers('admin_manager_approved')

    def action_director_approve(self):
        for req in self:
            if req.state != 'admin_manager_approved':
                raise UserError('Requisition must be approved by Admin Manager first!')
            req.state = 'director_approved'
            req.director_approval_date = fields.Datetime.now()
            req._notify_approvers('director_approved')

    def action_audit_approve(self):
        for req in self:
            if req.state != 'director_approved':
                raise UserError('Requisition must be approved by Director first!')
            req.state = 'audit_approved'
            req.audit_approval_date = fields.Datetime.now()
            req._create_stock_move()
            req._notify_issue_team()

    def action_reject(self):
        for req in self:
            if req.state in ['audit_approved']:
                raise UserError('Cannot reject an already approved requisition!')
            if not req.rejection_reason:
                raise UserError('Please provide a rejection reason!')
            req.state = 'rejected'

    def _create_stock_move(self):
        for req in self:
            if req.stock_move_id:
                return

            if req.product_id.product_type != 'asset' or not req.product_id.is_serial_tracked:
                cost_price = req.product_id.cost_price or 1.00
                source_location = False
                inventory_record = False

                if req.product_id.product_type == 'consumable':
                    admin_office = self._get_admin_office_location()

                    inventory = self.env['una.inventory'].search([
                        ('product_id', '=', req.product_id.id),
                        ('location_id', '=', admin_office.id)
                    ], limit=1)

                    if inventory and inventory.quantity_on_hand > 0:
                        source_location = admin_office.id
                        cost_price = inventory.product_id.cost_price or cost_price
                        inventory_record = inventory

                        if req.product_id.is_bundle and req.product_id.bundle_quantity > 0:
                            bundle_qty = inventory.quantity_on_hand / req.product_id.bundle_quantity
                            req.message_post(
                                body=f"📍 Found {inventory.quantity_on_hand} {req.product_id.uom_id.name} ({bundle_qty:.1f} {req.product_id.bundle_uom_id.name}) at {admin_office.name} (Central Store)"
                            )
                        else:
                            req.message_post(
                                body=f"📍 Found {inventory.quantity_on_hand} {req.product_id.name} at {admin_office.name} (Central Store)"
                            )

                    if not source_location and req.destination_location.id != admin_office.id:
                        inventory = self.env['una.inventory'].search([
                            ('product_id', '=', req.product_id.id),
                            ('location_id', '=', req.destination_location.id)
                        ], limit=1)

                        if inventory and inventory.quantity_on_hand > 0:
                            source_location = req.destination_location.id
                            cost_price = inventory.product_id.cost_price or cost_price
                            inventory_record = inventory

                            if req.product_id.is_bundle and req.product_id.bundle_quantity > 0:
                                bundle_qty = inventory.quantity_on_hand / req.product_id.bundle_quantity
                                req.message_post(
                                    body=f"📍 Found {inventory.quantity_on_hand} {req.product_id.uom_id.name} ({bundle_qty:.1f} {req.product_id.bundle_uom_id.name}) at {req.destination_location.name}"
                                )
                            else:
                                req.message_post(
                                    body=f"📍 Found {inventory.quantity_on_hand} {req.product_id.name} at {req.destination_location.name}"
                                )

                    if not source_location:
                        inventory = self.env['una.inventory'].search([
                            ('product_id', '=', req.product_id.id)
                        ], order='quantity_on_hand desc', limit=1)

                        if inventory and inventory.quantity_on_hand > 0:
                            source_location = inventory.location_id.id
                            cost_price = inventory.product_id.cost_price or cost_price
                            inventory_record = inventory

                            if req.product_id.is_bundle and req.product_id.bundle_quantity > 0:
                                bundle_qty = inventory.quantity_on_hand / req.product_id.bundle_quantity
                                req.message_post(
                                    body=f"📍 Found {inventory.quantity_on_hand} {req.product_id.uom_id.name} ({bundle_qty:.1f} {req.product_id.bundle_uom_id.name}) at {inventory.location_id.name} (fallback)"
                                )
                            else:
                                req.message_post(
                                    body=f"📍 Found {inventory.quantity_on_hand} {req.product_id.name} at {inventory.location_id.name} (fallback)"
                                )

                    if not source_location:
                        has_inventory = self.env['una.inventory'].search_count([
                            ('product_id', '=', req.product_id.id)
                        ])

                        if has_inventory:
                            inventory_records = self.env['una.inventory'].search([
                                ('product_id', '=', req.product_id.id)
                            ])
                            location_names = ', '.join(inv.location_id.name for inv in inventory_records)

                            raise UserError(
                                f"❌ No Stock Available\n\n"
                                f"{req.product_id.name} is out of stock at all locations.\n"
                                f"Locations: {location_names}\n\n"
                                f"💡 Please receive more stock at {admin_office.name} (central store) or your destination location."
                            )
                        else:
                            raise UserError(
                                f"❌ Product Not Received Yet\n\n"
                                f"{req.product_id.name} has not been received into inventory.\n\n"
                                f"💡 You need to:\n"
                                f"  1. Create a RECEIPT for {req.product_id.name}\n"
                                f"  2. Set destination to: {admin_office.name} (central store)\n"
                                f"  3. Enter the quantity you're receiving\n"
                                f"  4. Confirm the receipt\n"
                                f"  5. Then approve this requisition again"
                            )

                if req.product_id.product_type == 'asset':
                    available_asset = self.env['una.asset'].search([
                        ('product_id', '=', req.product_id.id),
                        ('status', '=', 'available')
                    ], limit=1)
                    if available_asset and available_asset.cost_price:
                        cost_price = available_asset.cost_price

                req.estimated_cost = cost_price
                actual_quantity = req.quantity

                move_vals = {
                    'product_id': req.product_id.id,
                    'move_type': 'issue',
                    'quantity': actual_quantity,
                    'destination_location': req.destination_location.id,
                    'cost_price_at_move': cost_price,
                    'reference': f"REQ-{req.name}",
                    'description': req.purpose,
                    'requisition_id': req.id,
                    'employee_id': req.employee_id.id,
                }

                if source_location:
                    move_vals['source_location'] = source_location

                stock_move = self.env['una.stock.move'].create(move_vals)

                if source_location and not stock_move.source_location:
                    stock_move.write({'source_location': source_location})
                    req.message_post(
                        body=f"📍 Source location forced set to: {stock_move.source_location.name if stock_move.source_location else 'N/A'}"
                    )

                if req.product_id.product_type == 'consumable':
                    stock_move.action_confirm()
                else:
                    stock_move.message_post(
                        body="📋 Stock move created. Admin review required for asset selection."
                    )

                req.stock_move_id = stock_move.id
                return

            available_assets = self.env['una.asset'].search([
                ('product_id', '=', req.product_id.id),
                ('status', '=', 'available')
            ], limit=int(req.quantity))

            if len(available_assets) < int(req.quantity):
                raise UserError(
                    f'Not enough available assets for {req.product_id.name}. '
                    f'Required: {int(req.quantity)}, Available: {len(available_assets)}'
                )

            locations = available_assets.mapped('current_location')

            if len(locations) == 1:
                cost_price = available_assets[0].cost_price or req.product_id.cost_price or 1.00
                req.estimated_cost = cost_price

                move_vals = {
                    'product_id': req.product_id.id,
                    'move_type': 'issue',
                    'quantity': len(available_assets),
                    'destination_location': req.destination_location.id,
                    'source_location': locations[0].id,
                    'cost_price_at_move': cost_price,
                    'reference': f"REQ-{req.name}",
                    'description': req.purpose,
                    'requisition_id': req.id,
                    'employee_id': req.employee_id.id,
                }

                stock_move = self.env['una.stock.move'].create(move_vals)
                stock_move.selected_asset_ids = [(6, 0, available_assets.ids)]
                stock_move.quantity = len(available_assets)
                stock_move.message_post(
                    body=f"📦 Stock move created with {len(available_assets)} assets from {locations[0].name}"
                )
                req.stock_move_id = stock_move.id

            else:
                moves_created = []
                total_cost = 0
                for location in locations:
                    location_assets = available_assets.filtered(lambda a: a.current_location.id == location.id)
                    if location_assets:
                        cost_price = location_assets[0].cost_price or req.product_id.cost_price or 1.00
                        total_cost += cost_price * len(location_assets)
                        move_vals = {
                            'product_id': req.product_id.id,
                            'move_type': 'issue',
                            'quantity': len(location_assets),
                            'destination_location': req.destination_location.id,
                            'source_location': location.id,
                            'cost_price_at_move': cost_price,
                            'reference': f"REQ-{req.name}-{location.name[:10]}",
                            'description': req.purpose,
                            'requisition_id': req.id,
                            'employee_id': req.employee_id.id,
                        }

                        stock_move = self.env['una.stock.move'].create(move_vals)
                        stock_move.selected_asset_ids = [(6, 0, location_assets.ids)]
                        stock_move.quantity = len(location_assets)
                        stock_move.message_post(
                            body=f"📦 Stock move created with {len(location_assets)} assets from {location.name}"
                        )
                        moves_created.append(stock_move)

                req.estimated_cost = total_cost

                if moves_created:
                    req.stock_move_id = moves_created[0].id
                    req.message_post(
                        body=f"📦 Created {len(moves_created)} stock moves for assets from different locations"
                    )

    @api.model
    def _get_admin_office_location(self):
        admin_office = self.env['una.location'].search([
            ('is_admin_office', '=', True),
            ('active', '=', True)
        ], limit=1)

        if admin_office:
            return admin_office

        admin_office = self.env['una.location'].search([
            ('name', 'ilike', 'ADMIN'),
            ('active', '=', True)
        ], limit=1)

        if admin_office:
            return admin_office

        return self.env['una.location'].search([
            ('active', '=', True)
        ], limit=1)

    def _get_ready_issue_email_body(self):
        """Generate the email body HTML for requisition ready to issue notification"""
        self.ensure_one()

        stock_move = self.stock_move_id
        requester_email = self.employee_id.work_email or self.employee_id.user_id.email or 'N/A'
        currency_symbol = self.currency_id.symbol or '$'
        estimated_cost_formatted = f"{currency_symbol}{'{:,.2f}'.format(self.estimated_cost)}"

        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <style>
                body {{ font-family: Arial, sans-serif; background-color: #f4f7fc; margin: 0; padding: 20px; }}
                .container {{ max-width: 650px; margin: 0 auto; background: #ffffff; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); overflow: hidden; }}
                .header {{ background: linear-gradient(135deg, #1a237e, #0d47a1); color: white; padding: 25px 30px; text-align: center; }}
                .header h1 {{ margin: 0; font-size: 24px; font-weight: 600; }}
                .header p {{ margin: 5px 0 0; opacity: 0.85; font-size: 14px; }}
                .body {{ padding: 30px; }}
                .status-badge {{ display: inline-block; background: #28a745; color: white; padding: 4px 14px; border-radius: 20px; font-size: 13px; font-weight: bold; }}
                .section-title {{ font-size: 16px; font-weight: 600; color: #1a237e; margin: 20px 0 10px; padding-bottom: 8px; border-bottom: 2px solid #e8eaf6; }}
                .info-box {{ background: #f0f4ff; border-left: 4px solid #1a237e; padding: 15px 20px; border-radius: 4px; margin: 15px 0; }}
                table {{ width: 100%; border-collapse: collapse; margin: 10px 0; font-size: 14px; }}
                th {{ background: #e8eaf6; padding: 10px 12px; text-align: left; font-weight: 600; color: #1a237e; border: 1px solid #dde1e6; }}
                td {{ padding: 10px 12px; border: 1px solid #dde1e6; }}
                tr:nth-child(even) {{ background: #f8f9fc; }}
                .action-btn {{ display: inline-block; background: #1a237e; color: white; text-decoration: none; padding: 12px 35px; border-radius: 6px; font-weight: 600; font-size: 15px; }}
                .action-btn:hover {{ background: #0d47a1; }}
                .action-btn-success {{ display: inline-block; background: #28a745; color: white; text-decoration: none; padding: 12px 35px; border-radius: 6px; font-weight: 600; font-size: 15px; }}
                .action-btn-success:hover {{ background: #218838; }}
                .footer {{ background: #f4f7fc; padding: 20px 30px; text-align: center; font-size: 12px; color: #777; border-top: 1px solid #e0e0e0; }}
                .footer a {{ color: #1a237e; text-decoration: none; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>📦 Requisition Ready for Issue</h1>
                    <p>UNA Inventory Management System</p>
                </div>
                <div class="body">
                    <p style="font-size: 16px; margin-top: 0;">
                        Dear Admin Team,
                    </p>
                    <p style="font-size: 14px; color: #333;">
                        Requisition <strong>{self.name}</strong> has been fully approved and is now ready for issue.
                        Please proceed with issuing the requested items.
                    </p>

                    <div style="text-align: center; margin: 20px 0;">
                        <span class="status-badge">✅ Approved - Ready for Issue</span>
                    </div>

                    <div class="section-title">📄 Requisition Details</div>
                    <table>
                        <tr><th style="width: 40%;">Field</th><th>Details</th></tr>
                        <tr><td><strong>Reference</strong></td><td>{self.name}</td></tr>
                        <tr><td><strong>Product</strong></td><td>{self.product_id.name}</td></tr>
                        <tr><td><strong>Quantity</strong></td><td>{self.quantity}</td></tr>
                        <tr><td><strong>Estimated Cost</strong></td><td>{estimated_cost_formatted}</td></tr>
                        <tr><td><strong>Destination Location</strong></td><td>{self.destination_location.name}</td></tr>
                        <tr><td><strong>Required By</strong></td><td>{self.required_date or 'N/A'}</td></tr>
                        <tr><td><strong>Purpose</strong></td><td>{self.purpose or 'N/A'}</td></tr>
                    </table>

                    <div class="section-title">👤 Requester Details</div>
                    <div class="info-box">
                        <table>
                            <tr><td style="border: none; padding: 5px 8px; width: 40%;"><strong>Name:</strong></td>
                                <td style="border: none; padding: 5px 8px;">{self.employee_id.name}</td></tr>
                            <tr><td style="border: none; padding: 5px 8px;"><strong>Department:</strong></td>
                                <td style="border: none; padding: 5px 8px;">{self.employee_id.department_id.name or 'N/A'}</td></tr>
                            <tr><td style="border: none; padding: 5px 8px;"><strong>Station:</strong></td>
                                <td style="border: none; padding: 5px 8px;">{self.employee_id.station_id.name or 'N/A'}</td></tr>
                            <tr><td style="border: none; padding: 5px 8px;"><strong>Email:</strong></td>
                                <td style="border: none; padding: 5px 8px;">
                                    <a href="mailto:{requester_email}" style="color: #1a237e; text-decoration: none;">
                                        {requester_email}
                                    </a>
                                </td></tr>
                        </table>
                    </div>

                    <div class="section-title">📦 Stock Move Details</div>
                    <div class="info-box">
                        <table>
                            <tr><td style="border: none; padding: 5px 8px; width: 40%;"><strong>Stock Move Reference:</strong></td>
                                <td style="border: none; padding: 5px 8px;">{stock_move.reference if stock_move else 'N/A'}</td></tr>
                            <tr><td style="border: none; padding: 5px 8px;"><strong>Product:</strong></td>
                                <td style="border: none; padding: 5px 8px;">{stock_move.product_id.name if stock_move else 'N/A'}</td></tr>
                            <tr><td style="border: none; padding: 5px 8px;"><strong>Quantity:</strong></td>
                                <td style="border: none; padding: 5px 8px;">{stock_move.quantity if stock_move else 'N/A'}</td></tr>
                            <tr><td style="border: none; padding: 5px 8px;"><strong>Status:</strong></td>
                                <td style="border: none; padding: 5px 8px;">{dict(stock_move._fields['state'].selection).get(stock_move.state, stock_move.state) if stock_move else 'N/A'}</td></tr>
                        </table>
                    </div>

                    <div style="text-align: center; margin: 25px 0;">
                        <a href="{self._get_approval_url()}" class="action-btn">
                           🔍 View Requisition
                        </a>
                        <a href="{self._get_stock_move_url()}" class="action-btn-success" style="margin-left: 10px;">
                           📦 View Stock Move
                        </a>
                    </div>

                    <div style="background: #d4edda; padding: 12px 18px; border-radius: 4px; border-left: 4px solid #28a745; margin: 15px 0;">
                        <p style="margin: 0; font-size: 13px; color: #155724;">
                            <strong>✅ Action Required:</strong> Please issue the items immediately.
                            <br/>
                            This requisition has been fully approved and is ready for processing.
                        </p>
                    </div>
                </div>
                <div class="footer">
                    <p>
                        This is an automated notification from <strong>UNA Inventory Management System</strong>.
                        <br/>
                        Requisition: <strong>{self.name}</strong>
                    </p>
                </div>
            </div>
        </body>
        </html>
        """
        return html

    def _notify_issue_team(self):
        """Send notification to Admin Assistant and Admin Manager to issue the requisition"""
        self.ensure_one()

        stock_move = self.stock_move_id
        if not stock_move:
            return

        admin_assistant = self._get_admin_assistant()
        admin_manager = self._get_admin_manager()

        email_list = []

        if admin_assistant:
            if admin_assistant.work_email:
                email_list.append(admin_assistant.work_email)
            elif admin_assistant.user_id and admin_assistant.user_id.email:
                email_list.append(admin_assistant.user_id.email)

        if admin_manager:
            if admin_manager.work_email:
                email_list.append(admin_manager.work_email)
            elif admin_manager.user_id and admin_manager.user_id.email:
                email_list.append(admin_manager.user_id.email)

        if not email_list:
            return

        template = self.env.ref('una_inventory_management.email_template_requisition_ready_issue',
                                raise_if_not_found=False)
        if template:
            try:
                template.sudo().send_mail(
                    self.id,
                    force_send=True,
                    raise_exception=False,
                    email_values={
                        'email_to': ', '.join(email_list),
                    }
                )
                self.message_post(body=f"📧 Notification sent to Admin Team for issuing requisition {self.name}")
            except Exception as e:
                self.message_post(body=f"⚠️ Could not send issue notification: {str(e)}")

    def _get_stock_move_url(self):
        """Get URL to view the stock move"""
        self.ensure_one()
        if not self.stock_move_id:
            return '#'
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        return f"{base_url}/web#id={self.stock_move_id.id}&model=una.stock.move&view_type=form"

    # === HELPERS FOR EMAIL TEMPLATE ===
    def _get_approver_email(self):
        """Get the email of the current approver based on state"""
        self.ensure_one()
        mapping = {
            'submitted': self.employee_id.parent_id,
            'line_manager_approved': self._get_admin_assistant(),
            'admin_assistant_approved': self._get_admin_manager(),
            'admin_manager_approved': self._get_director(),
            'director_approved': self._get_audit(),
        }
        approver = mapping.get(self.state)
        if approver:
            if hasattr(approver, 'work_email') and approver.work_email:
                return approver.work_email
            elif hasattr(approver, 'user_id') and approver.user_id and approver.user_id.email:
                return approver.user_id.email
            elif hasattr(approver, 'email'):
                return approver.email
        return ''

    def _get_approver_name(self):
        """Get the name of the current approver based on state"""
        self.ensure_one()
        mapping = {
            'submitted': self.employee_id.parent_id,
            'line_manager_approved': self._get_admin_assistant(),
            'admin_assistant_approved': self._get_admin_manager(),
            'admin_manager_approved': self._get_director(),
            'director_approved': self._get_audit(),
        }
        approver = mapping.get(self.state)
        if approver:
            if hasattr(approver, 'name'):
                return approver.name
        return 'Approver'

    def _get_approval_url(self):
        self.ensure_one()
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        return f"{base_url}/web#id={self.id}&model=una.requisition&view_type=form"

    def _get_email_body(self):
        """Generate the email body HTML for requisition approval"""
        self.ensure_one()

        approver_name = self._get_approver_name() or 'Approver'
        requester_email = self.employee_id.work_email or self.employee_id.user_id.email or 'N/A'
        currency_symbol = self.currency_id.symbol or '$'
        estimated_cost_formatted = f"{currency_symbol}{'{:,.2f}'.format(self.estimated_cost)}"
        approval_url = self._get_approval_url()

        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <style>
                body {{ font-family: Arial, sans-serif; background-color: #f4f7fc; margin: 0; padding: 20px; }}
                .container {{ max-width: 650px; margin: 0 auto; background: #ffffff; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); overflow: hidden; }}
                .header {{ background: linear-gradient(135deg, #1a237e, #0d47a1); color: white; padding: 25px 30px; text-align: center; }}
                .header h1 {{ margin: 0; font-size: 24px; font-weight: 600; }}
                .header p {{ margin: 5px 0 0; opacity: 0.85; font-size: 14px; }}
                .body {{ padding: 30px; }}
                .status-badge {{ display: inline-block; background: #ff9800; color: white; padding: 4px 14px; border-radius: 20px; font-size: 13px; font-weight: bold; }}
                .section-title {{ font-size: 16px; font-weight: 600; color: #1a237e; margin: 20px 0 10px; padding-bottom: 8px; border-bottom: 2px solid #e8eaf6; }}
                .requester-box {{ background: #f0f4ff; border-left: 4px solid #1a237e; padding: 15px 20px; border-radius: 4px; margin: 15px 0; }}
                table {{ width: 100%; border-collapse: collapse; margin: 10px 0; font-size: 14px; }}
                th {{ background: #e8eaf6; padding: 10px 12px; text-align: left; font-weight: 600; color: #1a237e; border: 1px solid #dde1e6; }}
                td {{ padding: 10px 12px; border: 1px solid #dde1e6; }}
                tr:nth-child(even) {{ background: #f8f9fc; }}
                .action-btn {{ display: inline-block; background: #1a237e; color: white; text-decoration: none; padding: 12px 35px; border-radius: 6px; font-weight: 600; font-size: 15px; }}
                .action-btn:hover {{ background: #0d47a1; }}
                .footer {{ background: #f4f7fc; padding: 20px 30px; text-align: center; font-size: 12px; color: #777; border-top: 1px solid #e0e0e0; }}
                .footer a {{ color: #1a237e; text-decoration: none; }}
                .highlight {{ color: #1a237e; font-weight: 600; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>📋 Requisition Approval Required</h1>
                    <p>UNA Inventory Management System</p>
                </div>

                <div class="body">
                    <p style="font-size: 16px; margin-top: 0;">
                        Dear <strong>{approver_name}</strong>,
                    </p>
                    <p style="font-size: 14px; color: #333;">
                        A requisition has been submitted and requires your approval.
                        Please review the details below and take appropriate action.
                    </p>

                    <div style="text-align: center; margin: 20px 0;">
                        <span class="status-badge">Awaiting Approval</span>
                    </div>

                    <div class="section-title">📄 Requisition Details</div>
                    <table>
                        <tr><th style="width: 40%;">Field</th><th>Details</th></tr>
                        <tr><td><strong>Reference</strong></td><td>{self.name}</td></tr>
                        <tr><td><strong>Product</strong></td><td>{self.product_id.name}</td></tr>
                        <tr><td><strong>Quantity</strong></td><td>{self.quantity}</td></tr>
                        <tr><td><strong>Estimated Cost</strong></td><td>{estimated_cost_formatted}</td></tr>
                        <tr><td><strong>Destination Location</strong></td><td>{self.destination_location.name}</td></tr>
                        <tr><td><strong>Required By</strong></td><td>{self.required_date or 'N/A'}</td></tr>
                        <tr><td><strong>Purpose / Reason</strong></td><td>{self.purpose or 'N/A'}</td></tr>
                    </table>

                    <div class="section-title">👤 Requester Details</div>
                    <div class="requester-box">
                        <table>
                            <tr><td style="border: none; padding: 5px 8px; width: 40%;"><strong>Name:</strong></td>
                                <td style="border: none; padding: 5px 8px;">{self.employee_id.name}</td></tr>
                            <tr><td style="border: none; padding: 5px 8px;"><strong>Department:</strong></td>
                                <td style="border: none; padding: 5px 8px;">{self.employee_id.department_id.name or 'N/A'}</td></tr>
                            <tr><td style="border: none; padding: 5px 8px;"><strong>Station:</strong></td>
                                <td style="border: none; padding: 5px 8px;">{self.employee_id.station_id.name or 'N/A'}</td></tr>
                            <tr><td style="border: none; padding: 5px 8px;"><strong>Email:</strong></td>
                                <td style="border: none; padding: 5px 8px;">
                                    <a href="mailto:{requester_email}" style="color: #1a237e; text-decoration: none;">
                                        {requester_email}
                                    </a>
                                </td></tr>
                        </table>
                    </div>

                    <div style="text-align: center; margin: 25px 0;">
                        <a href="{approval_url}" class="action-btn">
                           🔍 Review Requisition
                        </a>
                    </div>

                    <div style="background: #fff3e0; padding: 12px 18px; border-radius: 4px; border-left: 4px solid #ff9800; margin: 15px 0;">
                        <p style="margin: 0; font-size: 13px; color: #555;">
                            <strong>💡 Tip:</strong> You can approve or reject this requisition directly from the Odoo system.
                            <br/>
                            Please respond within <strong>24 hours</strong> to avoid escalation.
                        </p>
                    </div>
                </div>

                <div class="footer">
                    <p>
                        This is an automated notification from <strong>UNA Inventory Management System</strong>.
                        <br/>
                        Requisition: <strong>{self.name}</strong>
                        <br/>
                        <span style="font-size: 11px;">
                            If you have any questions, please contact the requester directly at
                            <a href="mailto:{requester_email}" style="color: #1a237e; text-decoration: none;">
                                {requester_email}
                            </a>.
                        </span>
                    </p>
                </div>
            </div>
        </body>
        </html>
        """
        return html

    # === NOTIFICATIONS ===
    def _notify_approvers(self, stage):
        for req in self:
            approver_mapping = {
                'submitted': ('Line Manager', req.employee_id.parent_id),
                'line_manager_approved': ('Admin Assistant', req._get_admin_assistant()),
                'admin_assistant_approved': ('Admin Manager', req._get_admin_manager()),
                'admin_manager_approved': ('Director of Admin', req._get_director()),
                'director_approved': ('Audit', req._get_audit()),
            }

            if stage in approver_mapping:
                stage_name, approver = approver_mapping[stage]
                if approver:
                    self.env['mail.activity'].create({
                        'activity_type_id': self.env.ref('mail.mail_activity_data_todo').id,
                        'user_id': approver.id,
                        'res_id': req.id,
                        'res_model_id': self.env['ir.model']._get('una.requisition').id,
                        'summary': f"Requisition {req.name} awaits your approval",
                        'note': f"""
                            Requisition: {req.name}
                            Product: {req.product_id.name}
                            Quantity: {req.quantity}
                            Cost: {req.estimated_cost}
                            Purpose: {req.purpose}
                            Requester: {req.employee_id.name}
                            Stage: {stage_name}
                        """,
                    })

                    approver_email = ''
                    if hasattr(approver, 'work_email') and approver.work_email:
                        approver_email = approver.work_email
                    elif hasattr(approver, 'user_id') and approver.user_id and approver.user_id.email:
                        approver_email = approver.user_id.email
                    elif hasattr(approver, 'email'):
                        approver_email = approver.email

                    if approver_email:
                        template = self.env.ref('una_inventory_management.email_template_requisition_approval')
                        if template:
                            template.send_mail(req.id, force_send=True, raise_exception=False,
                                               email_values={'email_to': approver_email})

    # === GET APPROVERS ===
    def _get_admin_assistant(self):
        return self.env.ref('base.user_admin', False)

    def _get_admin_manager(self):
        return self.env.ref('base.user_admin', False)

    def _get_director(self):
        return self.env.ref('base.user_admin', False)

    def _get_audit(self):
        return self.env.ref('base.user_admin', False)

    @api.model
    def _cron_check_pending_approvals(self):
        pending_states = [
            'submitted',
            'line_manager_approved',
            'admin_assistant_approved',
            'admin_manager_approved',
            'director_approved'
        ]

        pending = self.search([
            ('state', 'in', pending_states),
            ('write_date', '<=', fields.Datetime.now() - timedelta(hours=24))
        ])

        for req in pending:
            req.escalation_count += 1
            req.last_escalation_date = fields.Datetime.now()
            req._send_escalation_notification()

    def _send_escalation_notification(self):
        approver_mapping = {
            'submitted': self.employee_id.parent_id,
            'line_manager_approved': self._get_admin_assistant(),
            'admin_assistant_approved': self._get_admin_manager(),
            'admin_manager_approved': self._get_director(),
            'director_approved': self._get_audit(),
        }

        approver = approver_mapping.get(self.state)
        if approver:
            self.env['mail.activity'].create({
                'activity_type_id': self.env.ref('mail.mail_activity_data_todo').id,
                'user_id': approver.id,
                'res_id': self.id,
                'res_model_id': self.env['ir.model']._get('una.requisition').id,
                'summary': f"⚠️ ESCALATION: Requisition {self.name} pending > 24 hours",
                'note': f"""
                    This requisition has been pending for {self.escalation_count} escalations.
                    Please review and take action immediately.
                    Requisition: {self.name}
                    Product: {self.product_id.name}
                    Quantity: {self.quantity}
                    Purpose: {self.purpose}
                    Requester: {self.employee_id.name}
                """,
            })