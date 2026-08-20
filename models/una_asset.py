# from odoo import models, fields, api
# from odoo.exceptions import ValidationError, UserError
#
#
# class UnaAsset(models.Model):
#     _name = 'una.asset'
#     _description = 'UNA Asset'
#     _rec_name = 'name'
#     _order = 'create_date desc'
#
#     name = fields.Char(string='Asset Name', required=True)
#     product_id = fields.Many2one('una.product', string='Product', required=True)
#
#     # === SERIAL & TAG ===
#     serial_number = fields.Char(string='Serial Number', required=True)
#     asset_tag = fields.Char(string='Asset Tag', required=True, copy=False)
#
#     # === DATES ===
#     purchase_date = fields.Date(string='Purchase Date')
#
#     # === CURRENCY + COST ===
#     currency_id = fields.Many2one(
#         'res.currency',
#         string='Currency',
#         default=lambda self: self.env.company.currency_id,
#         required=True
#     )
#
#     cost_price = fields.Monetary(
#         string='Cost Price',
#         currency_field='currency_id',
#         default=0.0
#     )
#
#     current_location = fields.Many2one(
#         'una.location',
#         string='Current Location'
#     )
#     source_location = fields.Many2one(
#         'una.location',
#         string='Source Location',
#         compute='_compute_source_location',
#         store=False,
#         help="Location the asset came from (from last movement)"
#     )
#
#     last_move_date = fields.Datetime(
#         string='Last Movement Date',
#         compute='_compute_source_location',
#         store=False
#     )
#
#     is_admin = fields.Boolean(
#         string='Is Admin',
#         compute='_compute_is_admin',
#         store=False,
#         help="Technical field to check if user is Admin Assistant or Admin Manager"
#     )
#
#     @api.depends_context('uid')
#     def _compute_is_admin(self):
#         for rec in self:
#             user = self.env.user
#             is_admin = user.has_group('una_inventory_management.group_una_admin_assistant') or \
#                        user.has_group('una_inventory_management.group_una_admin_manager')
#             rec.is_admin = is_admin
#
#     def _compute_source_location(self):
#         for asset in self:
#             last_move = self.env['una.stock.move'].search([
#                 ('selected_asset_ids', 'in', asset.id),
#                 ('state', '=', 'confirmed')
#             ], order='move_date desc', limit=1)
#
#             if last_move:
#                 asset.source_location = last_move.source_location
#                 asset.last_move_date = last_move.move_date
#             else:
#                 asset.source_location = False
#                 asset.last_move_date = False
#
#     # === DISPLAY NAME ===
#     display_name = fields.Char(
#         string='Display Name',
#         compute='_compute_display_name',
#         store=True,
#         help="Shows asset tag and serial number together"
#     )
#
#     @api.depends('asset_tag', 'serial_number', 'current_location', 'status')
#     def _compute_display_name(self):
#         for asset in self:
#             location = asset.current_location.name if asset.current_location else 'No Location'
#             status = asset.status
#             asset.display_name = f"{asset.asset_tag} - {asset.serial_number} ({status}) - {location}"
#
#     # === ★ ADD THIS FIELD ===
#     change_asset = fields.Many2one(
#         'una.asset',
#         string='Change Asset',
#         domain="[('product_id', '=', product_id), ('status', '=', 'available')]",
#         help="Select another available asset to change serial and tag"
#     )
#
#     # === ★ ADD THIS ONCHANGE ===
#     @api.onchange('change_asset')
#     def _onchange_change_asset(self):
#         """When admin selects a different asset, copy its values"""
#         if self.change_asset:
#             ref = self.change_asset
#             self.serial_number = ref.serial_number
#             self.asset_tag = ref.asset_tag
#             self.name = ref.name
#             self.cost_price = ref.cost_price
#             self.current_location = ref.current_location
#             self.purchase_date = ref.purchase_date
#
#     status = fields.Selection([
#         ('available', 'Available'),
#         ('assigned', 'Assigned'),
#         ('scrapped', 'Scrapped')
#     ], string='Status', default='available')
#
#     # === ASSIGNMENT ===
#     assigned_to = fields.Many2one('hr.employee', string='Assigned To')
#     assigned_date = fields.Date(string='Assignment Date')
#
#     stock_move_id = fields.Many2one('una.stock.move', string='Stock Move')
#
#     _sql_constraints = [
#         ('unique_serial', 'unique(serial_number)', 'Serial number must be unique!'),
#         ('unique_asset_tag', 'unique(asset_tag)', 'Asset tag must be unique!')
#     ]
#
#     @api.constrains('cost_price')
#     def _check_cost_price(self):
#         for rec in self:
#             if rec.cost_price < 0:
#                 raise ValidationError('Cost price cannot be negative!')
#
#     @api.model
#     def _generate_asset_tag(self):
#         date_str = fields.Datetime.now().strftime('%Y%m%d')
#         count = self.search_count([]) + 1
#         return f"UNA-{date_str}-{count:04d}"
#
#     @api.model
#     def create(self, vals):
#         if not vals.get('asset_tag'):
#             vals['asset_tag'] = self._generate_asset_tag()
#         return super().create(vals)
#
#     # === NAME SEARCH ===
#     @api.model
#     def name_search(self, name, args=None, operator='ilike', limit=100):
#         """Search by asset_tag or serial_number"""
#         args = args or []
#         recs = self.browse()
#
#         if name:
#             recs = self.search([
#                                    '|',
#                                    ('asset_tag', operator, name),
#                                    ('serial_number', operator, name)
#                                ] + args, limit=limit)
#
#         if not recs:
#             recs = self.search([('name', operator, name)] + args, limit=limit)
#
#         if not recs:
#             recs = self.search(args, limit=limit)
#
#         return recs.name_get()
#
#     # === ACTIONS ===
#     def action_assign_simple(self):
#         """Simple assign without wizard - for testing"""
#         for asset in self:
#             if asset.status == 'scrapped':
#                 raise UserError('Cannot assign a scrapped asset!')
#             if asset.status == 'assigned':
#                 raise UserError('Asset is already assigned!')
#             asset.write({
#                 'status': 'assigned',
#                 'assigned_date': fields.Date.today(),
#             })
#             asset.message_post(body="✅ Asset assigned")
#
#     def action_make_available(self):
#         """Make asset available again"""
#         for asset in self:
#             if asset.status == 'scrapped':
#                 raise UserError('Cannot make a scrapped asset available!')
#             asset.write({
#                 'status': 'available',
#                 'assigned_to': False,
#                 'assigned_date': False,
#             })
#             asset.message_post(body="✅ Asset made available")
#
#     def action_scrap(self):
#         """Scrap the asset"""
#         for asset in self:
#             if asset.status == 'scrapped':
#                 raise UserError('Asset is already scrapped!')
#             asset.write({
#                 'status': 'scrapped',
#                 'assigned_to': False,
#                 'current_location': False,
#             })
#             asset.message_post(body="🗑️ Asset scrapped")
#
#     def _get_assignment_email_body(self):
#         """Generate the email body HTML for asset assignment"""
#         self.ensure_one()
#
#         assigned_to_name = self.assigned_to.name if self.assigned_to else 'Employee'
#         asset_url = self._get_asset_url()
#
#         html = f"""
#         <!DOCTYPE html>
#         <html>
#         <head>
#             <meta charset="UTF-8">
#             <style>
#                 body {{ font-family: Arial, sans-serif; background-color: #f4f7fc; margin: 0; padding: 20px; }}
#                 .container {{ max-width: 600px; margin: 0 auto; background: #ffffff; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); overflow: hidden; }}
#                 .header {{ background: linear-gradient(135deg, #1a237e, #0d47a1); color: white; padding: 25px 30px; text-align: center; }}
#                 .header h1 {{ margin: 0; font-size: 24px; font-weight: 600; }}
#                 .body {{ padding: 30px; }}
#                 .asset-box {{ background: #f0f4ff; border-left: 4px solid #1a237e; padding: 15px 20px; border-radius: 4px; margin: 15px 0; }}
#                 table {{ width: 100%; border-collapse: collapse; margin: 10px 0; font-size: 14px; }}
#                 th {{ background: #e8eaf6; padding: 10px 12px; text-align: left; font-weight: 600; color: #1a237e; border: 1px solid #dde1e6; }}
#                 td {{ padding: 10px 12px; border: 1px solid #dde1e6; }}
#                 .footer {{ background: #f4f7fc; padding: 20px 30px; text-align: center; font-size: 12px; color: #777; border-top: 1px solid #e0e0e0; }}
#                 .highlight {{ color: #1a237e; font-weight: 600; }}
#             </style>
#         </head>
#         <body>
#             <div class="container">
#                 <div class="header">
#                     <h1>📦 Asset Assigned to You</h1>
#                     <p>UNA Inventory Management System</p>
#                 </div>
#                 <div class="body">
#                     <p style="font-size: 16px; margin-top: 0;">
#                         Dear <strong>{assigned_to_name}</strong>,
#                     </p>
#                     <p style="font-size: 14px; color: #333;">
#                         An asset has been assigned to you. Please review the details below.
#                     </p>
#
#                     <div class="asset-box">
#                         <table>
#                             <tr><td style="border: none; padding: 5px 8px; width: 40%;"><strong>Asset:</strong></td>
#                                 <td style="border: none; padding: 5px 8px;">{self.name}</td></tr>
#                             <tr><td style="border: none; padding: 5px 8px;"><strong>Serial Number:</strong></td>
#                                 <td style="border: none; padding: 5px 8px;">{self.serial_number}</td></tr>
#                             <tr><td style="border: none; padding: 5px 8px;"><strong>Asset Tag:</strong></td>
#                                 <td style="border: none; padding: 5px 8px;">{self.asset_tag}</td></tr>
#                             <tr><td style="border: none; padding: 5px 8px;"><strong>Product:</strong></td>
#                                 <td style="border: none; padding: 5px 8px;">{self.product_id.name}</td></tr>
#                             <tr><td style="border: none; padding: 5px 8px;"><strong>Location:</strong></td>
#                                 <td style="border: none; padding: 5px 8px;">{self.current_location.name if self.current_location else 'N/A'}</td></tr>
#                             <tr><td style="border: none; padding: 5px 8px;"><strong>Assigned Date:</strong></td>
#                                 <td style="border: none; padding: 5px 8px;">{self.assigned_date}</td></tr>
#                         </table>
#                     </div>
#
#                     <div style="text-align: center; margin: 25px 0;">
#                         <a href="{asset_url}" style="display: inline-block; background: #1a237e; color: white; text-decoration: none; padding: 12px 35px; border-radius: 6px; font-weight: 600; font-size: 15px;">
#                            🔍 View Asset Details
#                         </a>
#                     </div>
#
#                     <div style="background: #fff3e0; padding: 12px 18px; border-radius: 4px; border-left: 4px solid #ff9800; margin: 15px 0;">
#                         <p style="margin: 0; font-size: 13px; color: #555;">
#                             <strong>💡 Note:</strong> This asset is now under your responsibility.
#                             Please keep it safe and report any issues to the Admin department.
#                         </p>
#                     </div>
#                 </div>
#                 <div class="footer">
#                     <p>
#                         This is an automated notification from <strong>UNA Inventory Management System</strong>.
#                         <br/>
#                         Asset: <strong>{self.serial_number}</strong>
#                     </p>
#                 </div>
#             </div>
#         </body>
#         </html>
#         """
#         return html
#
#     def _get_asset_url(self):
#         """Get URL to view the asset"""
#         self.ensure_one()
#         base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
#         return f"{base_url}/web#id={self.id}&model=una.asset&view_type=form"

from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError


class UnaAsset(models.Model):
    _name = 'una.asset'
    _description = 'UNA Asset'
    _rec_name = 'name'
    _order = 'create_date desc'

    name = fields.Char(string='Asset Name', required=True)
    product_id = fields.Many2one('una.product', string='Product', required=True)

    # === SERIAL & TAG ===
    serial_number = fields.Char(string='Serial Number', required=True)
    asset_tag = fields.Char(string='Asset Tag', required=True, copy=False)

    # === LOCATION-BASED TAGGING ===
    location_code = fields.Char(
        string='Location Code',
        compute='_compute_location_code',
        store=True,
        help="Short code based on current location (e.g., LAG-HQ, ABV-OFFICE)"
    )

    location_prefix = fields.Char(
        string='Location Prefix',
        compute='_compute_location_prefix',
        store=True,
        help="Prefix for asset tag based on location"
    )

    # === DATES ===
    purchase_date = fields.Date(string='Purchase Date')

    # === CURRENCY + COST ===
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id,
        required=True
    )

    cost_price = fields.Monetary(
        string='Cost Price',
        currency_field='currency_id',
        default=0.0
    )

    current_location = fields.Many2one(
        'una.location',
        string='Current Location'
    )
    source_location = fields.Many2one(
        'una.location',
        string='Source Location',
        compute='_compute_source_location',
        store=False,
        help="Location the asset came from (from last movement)"
    )

    last_move_date = fields.Datetime(
        string='Last Movement Date',
        compute='_compute_source_location',
        store=False
    )

    is_admin = fields.Boolean(
        string='Is Admin',
        compute='_compute_is_admin',
        store=False,
        help="Technical field to check if user is Admin Assistant or Admin Manager"
    )

    @api.depends_context('uid')
    def _compute_is_admin(self):
        for rec in self:
            user = self.env.user
            is_admin = user.has_group('una_inventory_management.group_una_admin_assistant') or \
                       user.has_group('una_inventory_management.group_una_admin_manager')
            rec.is_admin = is_admin

    def _compute_source_location(self):
        for asset in self:
            last_move = self.env['una.stock.move'].search([
                ('selected_asset_ids', 'in', asset.id),
                ('state', '=', 'confirmed')
            ], order='move_date desc', limit=1)

            if last_move:
                asset.source_location = last_move.source_location
                asset.last_move_date = last_move.move_date
            else:
                asset.source_location = False
                asset.last_move_date = False

    # === LOCATION CODE COMPUTATION ===
    @api.depends('current_location')
    def _compute_location_code(self):
        """Generate location code based on current location"""
        for asset in self:
            if asset.current_location:
                if asset.current_location.code:
                    asset.location_code = asset.current_location.code
                else:
                    # Generate from location name (e.g., "Lagos Headquarters" -> "LAG-HQ")
                    name_parts = asset.current_location.name.split()
                    code = ''
                    for part in name_parts[:2]:
                        code += part[:3].upper()
                    asset.location_code = code or 'UNK'
            else:
                asset.location_code = 'NO-LOC'

    @api.depends('current_location', 'location_code')
    def _compute_location_prefix(self):
        """Generate location prefix for asset tag"""
        for asset in self:
            if asset.current_location and asset.current_location.code:
                asset.location_prefix = asset.current_location.code
            elif asset.location_code:
                asset.location_prefix = asset.location_code
            else:
                asset.location_prefix = 'UNA'

    # === DISPLAY NAME ===
    display_name = fields.Char(
        string='Display Name',
        compute='_compute_display_name',
        store=True,
        help="Shows asset tag and serial number together"
    )

    @api.depends('asset_tag', 'serial_number', 'current_location', 'status', 'location_code')
    def _compute_display_name(self):
        for asset in self:
            location = asset.current_location.name if asset.current_location else 'No Location'
            status = asset.status
            loc_code = asset.location_code or 'N/A'
            asset.display_name = f"[{loc_code}] {asset.asset_tag} - {asset.serial_number} ({status})"

    # === CHANGE ASSET FIELD ===
    change_asset = fields.Many2one(
        'una.asset',
        string='Change Asset',
        domain="[('product_id', '=', product_id), ('status', '=', 'available')]",
        help="Select another available asset to change serial and tag"
    )

    # === ONCHANGE FOR CHANGE ASSET ===
    @api.onchange('change_asset')
    def _onchange_change_asset(self):
        """When admin selects a different asset, copy its values"""
        if self.change_asset:
            ref = self.change_asset
            self.serial_number = ref.serial_number
            self.asset_tag = ref.asset_tag
            self.name = ref.name
            self.cost_price = ref.cost_price
            self.current_location = ref.current_location
            self.purchase_date = ref.purchase_date

    status = fields.Selection([
        ('available', 'Available'),
        ('assigned', 'Assigned'),
        ('scrapped', 'Scrapped')
    ], string='Status', default='available')

    # === ASSIGNMENT ===
    assigned_to = fields.Many2one('hr.employee', string='Assigned To')
    assigned_date = fields.Date(string='Assignment Date')

    stock_move_id = fields.Many2one('una.stock.move', string='Stock Move')

    _sql_constraints = [
        ('unique_serial', 'unique(serial_number)', 'Serial number must be unique!'),
        ('unique_asset_tag', 'unique(asset_tag)', 'Asset tag must be unique!')
    ]

    @api.constrains('cost_price')
    def _check_cost_price(self):
        for rec in self:
            if rec.cost_price < 0:
                raise ValidationError('Cost price cannot be negative!')

    # === ASSET TAG GENERATION WITH LOCATION (MMYY FORMAT) ===
    @api.model
    def _generate_asset_tag(self, location_id=None):
        """Generate asset tag with location code and MMYY format (Month-Year)"""
        # Get location
        location = self.env['una.location'].browse(location_id) if location_id else False

        # Get location code
        if location and location.code:
            loc_code = location.code
        elif location:
            # Generate from name
            name_parts = location.name.split()
            loc_code = ''
            for part in name_parts[:2]:
                loc_code += part[:3].upper()
        else:
            loc_code = 'UNA'

        # ✅ MMYY format (Month-Year, e.g., 0824 for August 2024)
        date_str = fields.Datetime.now().strftime('%m%y')  # e.g., 0824 for August 2024

        # Get sequence
        count = self.search_count([]) + 1

        # Generate tag: LOC-MMYY-XXXX
        return f"{loc_code}-{date_str}-{count:04d}"

    @api.model
    def create(self, vals):
        # If location is provided, generate tag with location
        if not vals.get('asset_tag'):
            location_id = vals.get('current_location')
            vals['asset_tag'] = self._generate_asset_tag(location_id)

        # If location_code not set, compute it
        if 'location_code' not in vals and 'current_location' in vals:
            location = self.env['una.location'].browse(vals['current_location'])
            if location:
                vals['location_code'] = location.code or self._generate_location_code(location.name)

        return super().create(vals)

    def _generate_location_code(self, location_name):
        """Generate location code from name"""
        if not location_name:
            return 'UNK'
        name_parts = location_name.split()
        code = ''
        for part in name_parts[:2]:
            code += part[:3].upper()
        return code or 'UNK'

    # === NAME SEARCH ===
    @api.model
    def name_search(self, name, args=None, operator='ilike', limit=100):
        """Search by asset_tag, serial_number, or location"""
        args = args or []
        recs = self.browse()

        if name:
            recs = self.search([
                                   '|', '|',
                                   ('asset_tag', operator, name),
                                   ('serial_number', operator, name),
                                   ('location_code', operator, name)
                               ] + args, limit=limit)

        if not recs:
            recs = self.search([('name', operator, name)] + args, limit=limit)

        if not recs:
            recs = self.search(args, limit=limit)

        return recs.name_get()

    # === ACTIONS ===
    def action_assign_simple(self):
        """Simple assign without wizard - for testing"""
        for asset in self:
            if asset.status == 'scrapped':
                raise UserError('Cannot assign a scrapped asset!')
            if asset.status == 'assigned':
                raise UserError('Asset is already assigned!')
            asset.write({
                'status': 'assigned',
                'assigned_date': fields.Date.today(),
            })
            asset.message_post(body="✅ Asset assigned")

    def action_make_available(self):
        """Make asset available again"""
        for asset in self:
            if asset.status == 'scrapped':
                raise UserError('Cannot make a scrapped asset available!')
            asset.write({
                'status': 'available',
                'assigned_to': False,
                'assigned_date': False,
            })
            asset.message_post(body="✅ Asset made available")

    def action_scrap(self):
        """Scrap the asset"""
        for asset in self:
            if asset.status == 'scrapped':
                raise UserError('Asset is already scrapped!')
            asset.write({
                'status': 'scrapped',
                'assigned_to': False,
                'current_location': False,
            })
            asset.message_post(body="🗑️ Asset scrapped")

    def _get_assignment_email_body(self):
        """Generate the email body HTML for asset assignment"""
        self.ensure_one()

        assigned_to_name = self.assigned_to.name if self.assigned_to else 'Employee'
        asset_url = self._get_asset_url()
        location = self.current_location.name if self.current_location else 'Not assigned'
        loc_code = self.location_code or 'N/A'

        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <style>
                body {{ font-family: Arial, sans-serif; background-color: #f4f7fc; margin: 0; padding: 20px; }}
                .container {{ max-width: 600px; margin: 0 auto; background: #ffffff; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); overflow: hidden; }}
                .header {{ background: linear-gradient(135deg, #1a237e, #0d47a1); color: white; padding: 25px 30px; text-align: center; }}
                .header h1 {{ margin: 0; font-size: 24px; font-weight: 600; }}
                .body {{ padding: 30px; }}
                .asset-box {{ background: #f0f4ff; border-left: 4px solid #1a237e; padding: 15px 20px; border-radius: 4px; margin: 15px 0; }}
                table {{ width: 100%; border-collapse: collapse; margin: 10px 0; font-size: 14px; }}
                th {{ background: #e8eaf6; padding: 10px 12px; text-align: left; font-weight: 600; color: #1a237e; border: 1px solid #dde1e6; }}
                td {{ padding: 10px 12px; border: 1px solid #dde1e6; }}
                .footer {{ background: #f4f7fc; padding: 20px 30px; text-align: center; font-size: 12px; color: #777; border-top: 1px solid #e0e0e0; }}
                .highlight {{ color: #1a237e; font-weight: 600; }}
                .location-badge {{ display: inline-block; background: #1a237e; color: white; padding: 2px 12px; border-radius: 12px; font-size: 12px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>📦 Asset Assigned to You</h1>
                    <p>United Nigeria Airlines - Inventory Management</p>
                </div>
                <div class="body">
                    <p style="font-size: 16px; margin-top: 0;">
                        Dear <strong>{assigned_to_name}</strong>,
                    </p>
                    <p style="font-size: 14px; color: #333;">
                        An asset has been assigned to you. Please review the details below.
                    </p>

                    <div class="asset-box">
                        <table>
                            <tr><td style="border: none; padding: 5px 8px; width: 40%;"><strong>Asset:</strong></td>
                                <td style="border: none; padding: 5px 8px;">{self.name}</td></tr>
                            <tr><td style="border: none; padding: 5px 8px;"><strong>Serial Number:</strong></td>
                                <td style="border: none; padding: 5px 8px;">{self.serial_number}</td></tr>
                            <tr><td style="border: none; padding: 5px 8px;"><strong>Asset Tag:</strong></td>
                                <td style="border: none; padding: 5px 8px;"><span class="location-badge">{self.asset_tag}</span></td></tr>
                            <tr><td style="border: none; padding: 5px 8px;"><strong>Location Code:</strong></td>
                                <td style="border: none; padding: 5px 8px;"><span class="location-badge">{loc_code}</span></td></tr>
                            <tr><td style="border: none; padding: 5px 8px;"><strong>Product:</strong></td>
                                <td style="border: none; padding: 5px 8px;">{self.product_id.name}</td></tr>
                            <tr><td style="border: none; padding: 5px 8px;"><strong>Location:</strong></td>
                                <td style="border: none; padding: 5px 8px;">{location}</td></tr>
                            <tr><td style="border: none; padding: 5px 8px;"><strong>Assigned Date:</strong></td>
                                <td style="border: none; padding: 5px 8px;">{self.assigned_date}</td></tr>
                        </table>
                    </div>

                    <div style="text-align: center; margin: 25px 0;">
                        <a href="{asset_url}" style="display: inline-block; background: #1a237e; color: white; text-decoration: none; padding: 12px 35px; border-radius: 6px; font-weight: 600; font-size: 15px;">
                           🔍 View Asset Details
                        </a>
                    </div>

                    <div style="background: #fff3e0; padding: 12px 18px; border-radius: 4px; border-left: 4px solid #ff9800; margin: 15px 0;">
                        <p style="margin: 0; font-size: 13px; color: #555;">
                            <strong>💡 Note:</strong> This asset is now under your responsibility.
                            Please keep it safe and report any issues to the Admin department.
                        </p>
                    </div>
                </div>
                <div class="footer">
                    <p>
                        This is an automated notification from <strong>United Nigeria Airlines</strong>.
                        <br/>
                        Asset: <strong>{self.serial_number}</strong> | Location: <strong>{location}</strong>
                    </p>
                </div>
            </div>
        </body>
        </html>
        """
        return html

    def _get_asset_url(self):
        """Get URL to view the asset"""
        self.ensure_one()
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        return f"{base_url}/web#id={self.id}&model=una.asset&view_type=form"
