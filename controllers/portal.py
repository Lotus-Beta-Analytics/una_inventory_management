import logging
from odoo import http, models, fields
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal

_logger = logging.getLogger(__name__)


class UnaPortalRequisition(CustomerPortal):

    def _prepare_requisition_domain(self):
        """Prepare domain for requisitions based on user"""
        user = request.env.user
        if user.has_group('una_inventory_management.group_una_admin_assistant') or \
                user.has_group('una_inventory_management.group_una_admin_manager') or \
                user.has_group('una_inventory_management.group_una_line_manager'):
            return []
        return [('employee_id.user_id', '=', user.id)]

    # ================================================================
    # REQUISITION ROUTES
    # ================================================================

    @http.route(['/my/requisitions', '/my/requisitions/', '/my/requisitions/page/<int:page>'],
                type='http', auth='user', website=True)
    def portal_my_requisitions(self, page=1, **kwargs):
        """Display user's requisitions on portal"""
        try:
            domain = self._prepare_requisition_domain()
            requisitions = request.env['una.requisition'].sudo().search(domain, order='create_date desc')

            success = kwargs.get('success', '')
            success_message = success == 'created'

            values = {
                'requisitions': requisitions,
                'page_name': 'requisitions',
                'success_message': success_message,
            }
            return request.render('una_inventory_management.portal_my_requisitions', values)
        except Exception as e:
            _logger.error(f"Error in portal_my_requisitions: {e}")
            return request.render('una_inventory_management.portal_error', {
                'error_message': str(e),
                'page_name': 'error'
            })

    @http.route(['/my/requisition/<int:requisition_id>', '/my/requisition/<int:requisition_id>/'],
                type='http', auth='user', website=True)
    def portal_requisition_detail(self, requisition_id, **kwargs):
        """Display requisition detail on portal"""
        try:
            requisition = request.env['una.requisition'].sudo().browse(requisition_id)

            if not requisition.exists():
                return request.redirect('/my/requisitions')

            if requisition.employee_id.user_id != request.env.user and \
                    not request.env.user.has_group('una_inventory_management.group_una_admin_assistant'):
                return request.redirect('/my/requisitions')

            values = {
                'requisition': requisition,
                'page_name': 'requisition_detail',
            }
            return request.render('una_inventory_management.portal_requisition_detail', values)
        except Exception as e:
            _logger.error(f"Error in portal_requisition_detail: {e}")
            return request.redirect('/my/requisitions')

    @http.route(['/my/requisition/new', '/my/requisition/new/'], type='http', auth='user', website=True)
    def portal_requisition_new(self, **kwargs):
        """Create new requisition form on portal"""
        try:
            products = request.env['una.product'].sudo().search([('active', '=', True)])
            locations = request.env['una.location'].sudo().search([('active', '=', True)])
            employee = request.env.user.employee_id

            error = kwargs.get('error', '')
            success = kwargs.get('success', '')

            _logger.info(f"Loading new requisition form - Products: {len(products)}, Locations: {len(locations)}")

            values = {
                'products': products,
                'locations': locations,
                'employee': employee,
                'employee_department': employee.department_id.name if employee.department_id else 'N/A',
                'employee_station': employee.station_id.name if employee.station_id else 'N/A',
                'page_name': 'new_requisition',
                'error': error,
                'success': success,
            }
            return request.render('una_inventory_management.portal_requisition_new', values)
        except Exception as e:
            _logger.error(f"Error in portal_requisition_new: {e}")
            return request.redirect('/my/requisitions')

    @http.route(['/my/requisition/create', '/my/requisition/create/'], type='http', auth='user', website=True, methods=['POST'])
    def portal_requisition_create(self, **post):
        """Create new requisition from portal"""
        if not post.get('product_id') or not post.get('quantity') or not post.get('destination_location'):
            return request.redirect('/my/requisition/new?error=missing_fields')

        try:
            requisition_vals = {
                'employee_id': request.env.user.employee_id.id,
                'product_id': int(post.get('product_id')),
                'quantity': float(post.get('quantity')),
                'destination_location': int(post.get('destination_location')),
                'purpose': post.get('purpose', ''),
                'required_date': post.get('required_date'),
                'state': 'draft'
            }

            requisition = request.env['una.requisition'].sudo().create(requisition_vals)
            requisition.action_submit()

            return request.redirect('/my/requisitions?success=created')
        except Exception as e:
            _logger.error(f"Error creating requisition: {e}")
            return request.redirect(f'/my/requisition/new?error={str(e)}')

    @http.route(['/my/requisition/cancel/<int:requisition_id>', '/my/requisition/cancel/<int:requisition_id>/'],
                type='http', auth='user', website=True, methods=['POST'])
    def portal_requisition_cancel(self, requisition_id, **post):
        """Cancel a requisition from portal"""
        try:
            requisition = request.env['una.requisition'].sudo().browse(requisition_id)

            if requisition.exists() and requisition.state in ['draft', 'submitted']:
                requisition.write({
                    'state': 'rejected',
                    'rejection_reason': 'Cancelled by employee'
                })
                requisition.message_post(body="❌ Requisition cancelled by employee")

            return request.redirect('/my/requisitions')
        except Exception as e:
            _logger.error(f"Error cancelling requisition: {e}")
            return request.redirect('/my/requisitions')

    # ================================================================
    # REQUISITION HISTORY ROUTE
    # ================================================================

    @http.route(['/my/requisitions/history', '/my/requisitions/history/'],
                type='http', auth='user', website=True)
    def portal_requisition_history(self, **kwargs):
        """Display user's requisition history"""
        try:
            domain = self._prepare_requisition_domain()
            history_requisitions = request.env['una.requisition'].sudo().search(
                domain + ['|', ('state', 'in', ['audit_approved', 'rejected']), ('state', '=', 'cancelled')],
                order='write_date desc'
            )

            values = {
                'history_requisitions': history_requisitions,
                'page_name': 'requisition_history',
            }
            return request.render('una_inventory_management.portal_requisition_history', values)
        except Exception as e:
            _logger.error(f"Error in portal_requisition_history: {e}")
            return request.redirect('/my/requisitions')

    # ================================================================
    # DAMAGE REPORTS TAB ROUTE - ★ ADD THIS
    # ================================================================

    @http.route(['/my/requisitions/damage-reports', '/my/requisitions/damage-reports/'],
                type='http', auth='user', website=True)
    def portal_requisition_damage_reports(self, **kwargs):
        """Display damage reports within requisitions tab"""
        try:
            damage_reports = request.env['una.asset.damage.report'].sudo().search([
                ('employee_id', '=', request.env.user.employee_id.id)
            ], order='reported_date desc')

            values = {
                'damage_reports': damage_reports,
                'page_name': 'damage_reports',
            }
            return request.render('una_inventory_management.portal_requisition_damage_reports', values)
        except Exception as e:
            _logger.error(f"Error in portal_requisition_damage_reports: {e}")
            return request.redirect('/my/requisitions')

    # ================================================================
    # ASSET DAMAGE REPORT ROUTES
    # ================================================================

    # @http.route(['/my/asset/damage-report', '/my/asset/damage-report/'],
    #             type='http', auth='user', website=True)
    # def portal_asset_damage_report_form(self, **kwargs):
    #     """Display asset damage report form"""
    #     try:
    #         assigned_assets = request.env['una.asset'].sudo().search([
    #             ('assigned_to', '=', request.env.user.employee_id.id),
    #             ('status', '=', 'assigned')
    #         ])
    #
    #         error = kwargs.get('error', '')
    #         success = kwargs.get('success', '')
    #
    #         values = {
    #             'assigned_assets': assigned_assets,
    #             'page_name': 'damage_report',
    #             'error': error,
    #             'success': success,
    #         }
    #         return request.render('una_inventory_management.portal_asset_damage_report', values)
    #     except Exception as e:
    #         _logger.error(f"Error in portal_asset_damage_report_form: {e}")
    #         return request.redirect('/my/requisitions')
    @http.route(['/my/asset/damage-report', '/my/asset/damage-report/'],
                type='http', auth='user', website=True)
    def portal_asset_damage_report_form(self, **kwargs):
        try:
            # REMOVE the assigned_to filter - show all assigned assets
            assigned_assets = request.env['una.asset'].sudo().search([
                ('status', '=', 'assigned')
            ])

            error = kwargs.get('error', '')
            success = kwargs.get('success', '')

            values = {
                'assigned_assets': assigned_assets,
                'page_name': 'damage_report',
                'error': error,
                'success': success,
            }
            return request.render('una_inventory_management.portal_asset_damage_report', values)
        except Exception as e:
            _logger.error(f"Error in portal_asset_damage_report_form: {e}")
            return request.redirect('/my/requisitions')

    @http.route('/my/asset/damage-report/submit', type='http', auth='user', website=True, methods=['POST'])
    def portal_asset_damage_report_submit(self, **post):
        """Submit asset damage report"""
        try:
            asset_id = post.get('asset_id')
            damage_description = post.get('damage_description', '')
            damage_severity = post.get('damage_severity', 'minor')

            if not asset_id:
                return request.redirect('/my/asset/damage-report?error=missing_asset')

            if not damage_description:
                return request.redirect('/my/asset/damage-report?error=missing_description')

            asset = request.env['una.asset'].sudo().browse(int(asset_id))

            if not asset.exists():
                return request.redirect('/my/asset/damage-report?error=asset_not_found')

            if asset.status != 'assigned':
                return request.redirect('/my/asset/damage-report?error=asset_not_assigned')

            damage_report_vals = {
                'asset_id': asset.id,
                'employee_id': request.env.user.employee_id.id,
                'damage_description': damage_description,
                'damage_severity': damage_severity,
                'reported_date': fields.Datetime.now(),
                'status': 'submitted',
                'source': 'portal',
            }

            damage_report = request.env['una.asset.damage.report'].sudo().create(damage_report_vals)

            stock_move_vals = {
                'product_id': asset.product_id.id,
                'move_type': 'scrap',
                'quantity': 1,
                'source_location': asset.current_location.id if asset.current_location else False,
                'destination_location': False,
                'cost_price_at_move': asset.cost_price or 0.0,
                'description': f"Damage report: {damage_description}",
                'selected_asset_ids': [(6, 0, [asset.id])],
                'state': 'draft',
            }

            stock_move = request.env['una.stock.move'].sudo().create(stock_move_vals)

            damage_report.write({
                'stock_move_id': stock_move.id,
            })

            return request.redirect('/my/asset/damage-report?success=submitted')

        except Exception as e:
            _logger.error(f"Error submitting damage report: {e}")
            return request.redirect(f'/my/asset/damage-report?error={str(e)}')