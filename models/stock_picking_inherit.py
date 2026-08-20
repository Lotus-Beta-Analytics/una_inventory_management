from odoo import models, fields, api
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class StockPickingInherit(models.Model):
    _inherit = 'stock.picking'

    # === NEW FIELDS FOR UNA SYNC TRACKING ===
    una_sync_status = fields.Selection([
        ('not_synced', 'Not Synced'),
        ('synced', 'Synced to UNA'),
        ('failed', 'Sync Failed')
    ], string='UNA Sync Status', default='not_synced', copy=False)

    una_stock_move_ids = fields.One2many(
        'una.stock.move',
        'purchase_picking_id',
        string='UNA Receipts',
        readonly=True
    )
    una_sync_error = fields.Text(
        string='Sync Error',
        readonly=True
    )
    una_synced_date = fields.Datetime(
        string='Synced Date',
        readonly=True
    )

    # === OVERRIDE CONFIRM METHOD ===
    def action_confirm(self):
        """When picking is confirmed, sync to UNA"""
        result = super().action_confirm()
        for picking in self:
            if picking.picking_type_code == 'incoming':
                picking._sync_to_una()
        return result

    # === MAIN SYNC METHOD ===
    def _sync_to_una(self):
        for picking in self:
            # Skip if not an incoming shipment
            if picking.picking_type_code != 'incoming':
                continue

            # Skip if already synced
            if picking.una_sync_status == 'synced':
                _logger.info(f"Picking {picking.name} already synced to UNA")
                continue

            try:
                # Get ADMIN CENTRAL OFFICE
                admin_office = self._get_admin_office_location()

                # Get or create vendor location
                vendor_location = self._get_or_create_vendor_location(picking.partner_id)

                synced_moves = []

                # ✅ FIXED: Use move_ids instead of move_lines (Odoo 17+)
                for move_line in picking.move_ids:
                    if move_line.product_uom_qty <= 0:
                        continue

                    # 1. Sync product to UNA
                    una_product = self._sync_product_to_una(move_line.product_id)

                    if una_product:
                        # 2. Create UNA receipt in DRAFT state
                        una_receipt = self._create_una_receipt(
                            picking,
                            move_line,
                            una_product,
                            vendor_location,
                            admin_office
                        )

                        if una_receipt:
                            synced_moves.append(una_receipt.reference)
                            self.una_stock_move_ids = [(4, una_receipt.id)]

                # Mark as synced
                if synced_moves:
                    picking.una_sync_status = 'synced'
                    picking.una_synced_date = fields.Datetime.now()
                    picking.message_post(
                        body=f"✅ Auto-synced to UNA system.\n"
                             f"Receipts created: {', '.join(synced_moves)}\n"
                             f"📋 Please go to 'Pending Receipt into Inventory' menu to confirm."
                    )
                else:
                    picking.una_sync_status = 'failed'
                    picking.una_sync_error = 'No valid move lines to sync'

            except Exception as e:
                picking.una_sync_status = 'failed'
                picking.una_sync_error = str(e)
                picking.message_post(
                    body=f"❌ Sync failed: {str(e)}"
                )
                _logger.error(f"UNA Sync failed for picking {picking.name}: {str(e)}")
                raise

    # === HELPER: Get ADMIN CENTRAL OFFICE ===
    def _get_admin_office_location(self):
        """Get or create ADMIN CENTRAL OFFICE location"""
        admin_office = self.env['una.location'].search([
            ('is_admin_office', '=', True),
            ('active', '=', True)
        ], limit=1)

        if not admin_office:
            # Create if doesn't exist
            admin_office = self.env['una.location'].create({
                'name': 'ADMIN CENTRAL OFFICE',
                'code': 'ADMIN-CENTRAL',
                'is_admin_office': True,
                'active': True,
            })
            _logger.info("Created ADMIN CENTRAL OFFICE location")

        return admin_office

    # === HELPER: Get or Create Vendor Location ===
    def _get_or_create_vendor_location(self, partner):
        """Get or create vendor location from partner"""
        if not partner:
            # Fallback: create a generic vendor location
            vendor_location = self.env['una.location'].search([
                ('is_vendor_location', '=', True),
                ('name', '=', 'External Vendor')
            ], limit=1)

            if not vendor_location:
                vendor_location = self.env['una.location'].create({
                    'name': 'External Vendor',
                    'code': 'VENDOR-EXTERNAL',
                    'is_vendor_location': True,
                    'active': True,
                })
            return vendor_location

        vendor_location = self.env['una.location'].search([
            ('partner_id', '=', partner.id),
            ('is_vendor_location', '=', True)
        ], limit=1)

        if not vendor_location:
            vendor_location = self.env['una.location'].create({
                'name': f"{partner.name} (Vendor)",
                'code': f"VENDOR-{partner.id}",
                'is_vendor_location': True,
                'partner_id': partner.id,
                'active': True,
            })

        return vendor_location

    # === HELPER: Sync Product to UNA ===
    def _sync_product_to_una(self, product):
        """Sync Odoo product to UNA product"""
        # Check if UNA product already exists
        una_product = self.env['una.product'].search([
            ('odoo_product_id', '=', product.id)
        ], limit=1)

        if not una_product:
            # Determine product type
            product_type = 'asset' if product.tracking == 'serial' else 'consumable'

            # Get UOM
            uom_id = product.uom_id.id or False

            # ✅ FIX: Ensure cost_price is at least 1.0
            cost_price = product.standard_price or 1.0

            una_product = self.env['una.product'].create({
                'name': product.name,
                'product_type': product_type,
                'cost_price': cost_price,
                'uom_id': uom_id,
                'is_serial_tracked': product.tracking == 'serial',
                'odoo_product_id': product.id,
                'active': True,
                'code': product.default_code or f"PROD-{product.id}",
            })

            _logger.info(f"Created UNA product: {una_product.name} (from Odoo product {product.id}, cost: {cost_price})")

        return una_product


    def _create_una_receipt(self, picking, move_line, una_product, vendor_location, admin_office):

        # ✅ FIX: Ensure cost_price is at least 1.0
        cost_price = move_line.price_unit or move_line.product_id.standard_price or 1.0

        # For serial tracked products
        is_serial = move_line.product_id.tracking == 'serial'

        # Get purchase order reference
        po_reference = picking.origin or 'Unknown PO'

        receipt_vals = {
            'product_id': una_product.id,
            'move_type': 'receipt',
            'quantity': move_line.product_uom_qty,
            'source_location': vendor_location.id,
            'destination_location': admin_office.id,
            'cost_price_at_move': cost_price,
            'reference': f"PO-{po_reference}",
            'description': (
                f"Auto-created from Purchase Order: {po_reference}\n"
                f"Vendor: {picking.partner_id.name if picking.partner_id else 'Unknown'}\n"
                f"Unit Price: {cost_price}\n"
                f"Total Cost: {cost_price * move_line.product_uom_qty}\n"
                f"Received Date: {fields.Datetime.now()}\n"
                f"Original PO: {po_reference}"
            ),
            'state': 'draft',
            'purchase_picking_id': picking.id,
            'purchase_order_id': picking.purchase_id.id if picking.purchase_id else False,
            'odoo_product_id': move_line.product_id.id,
            'is_serial_tracked': is_serial,
            'is_auto_created': True,
            'employee_id': False,
        }

        # If serial tracked, set entry method
        if is_serial:
            receipt_vals['serial_entry_method'] = 'single'
            receipt_vals['description'] += (
                f"\n\n⚠️ SERIAL TRACKED PRODUCT\n"
                f"Please enter serial numbers when confirming this receipt."
            )

        una_receipt = self.env['una.stock.move'].create(receipt_vals)

        # Post message on receipt
        una_receipt.message_post(
            body=(
                f"📥 Auto-created from Purchase Order: {po_reference}\n"
                f"Vendor: {picking.partner_id.name if picking.partner_id else 'Unknown'}\n"
                f"Product: {una_product.name}\n"
                f"Quantity: {move_line.product_uom_qty}\n"
                f"Unit Price: {cost_price}\n"
                f"Total Cost: {move_line.product_uom_qty}\n"
                f"Destination: ADMIN CENTRAL OFFICE\n"
                f"Status: DRAFT - Awaiting confirmation\n\n"
                f"📋 Please review and confirm this receipt."
            )
        )

        _logger.info(f"Created UNA receipt: {una_receipt.reference} (move {una_receipt.id})")

        # ================================================================
        # ✅ SEND EMAIL NOTIFICATION TO ADMIN TEAM (ADDED)
        # ================================================================
        try:
            # Get the email template
            template = self.env.ref('una_inventory_management.email_template_pending_receipt', raise_if_not_found=False)

            if template:
                # Send the email
                template.send_mail(una_receipt.id, force_send=True, raise_exception=False)
                _logger.info(f"📧 Pending receipt notification email sent for {una_receipt.reference}")
            else:
                _logger.warning(f"⚠️ Email template not found for pending receipt notification")

        except Exception as e:
            _logger.error(f"❌ Failed to send email for {una_receipt.reference}: {str(e)}")

        return una_receipt