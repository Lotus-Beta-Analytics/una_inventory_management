from odoo import models, fields, api
from odoo.exceptions import ValidationError


class UnaLocation(models.Model):
    _name = 'una.location'
    _description = 'UNA Location'
    _rec_name = 'name'
    _order = 'name'

    name = fields.Char(string='Location Name', required=True)
    code = fields.Char(string='Location Code', required=True, unique=True)
    active = fields.Boolean(string='Active', default=True)

    station_id = fields.Many2one(
        'hr.employee.station',
        string='Station',
        help="Associated station for this location"
    )

    warehouse_id = fields.Many2one(
        'una.warehouse',
        string='Warehouse',
        help="Parent warehouse for this location"
    )

    is_admin_office = fields.Boolean(
        string='Is Admin Office',
        default=False,
        help="Mark this location as the main Admin Office (central store)"
    )

    # ✅ ADDED: Vendor location fields for purchase order integration
    is_vendor_location = fields.Boolean(
        string='Is Vendor Location',
        default=False,
        help="Mark this location as a vendor/supplier location"
    )

    partner_id = fields.Many2one(
        'res.partner',
        string='Vendor/Supplier',
        help="Associated vendor for this location"
    )

    # ★ Parent Location
    parent_location_id = fields.Many2one(
        'una.location',
        string='Parent Location',
        domain="[('id', '!=', id)]",
        help="Parent location for hierarchical organization. Warehouse and Station will be inherited."
    )

    # ★ Child Locations
    child_location_ids = fields.One2many(
        'una.location',
        'parent_location_id',
        string='Child Locations'
    )

    display_name = fields.Char(
        string='Display Name',
        compute='_compute_display_name',
        store=True,
    )

    @api.depends('name', 'station_id', 'station_id.name', 'warehouse_id', 'warehouse_id.name', 'parent_location_id')
    def _compute_display_name(self):
        for record in self:
            if record.parent_location_id:
                # Use parent's display_name and append current name
                record.display_name = f"{record.parent_location_id.display_name} / {record.name}"
            else:
                parts = []
                if record.warehouse_id:
                    parts.append(record.warehouse_id.name)
                if record.station_id:
                    parts.append(record.station_id.name)
                if record.name:
                    parts.append(record.name)
                record.display_name = ' / '.join(parts) if parts else record.name

    # ★ Auto-inherit warehouse and station from parent
    @api.onchange('parent_location_id')
    def _onchange_parent_location_id(self):
        if self.parent_location_id:
            # Inherit warehouse from parent
            if self.parent_location_id.warehouse_id:
                self.warehouse_id = self.parent_location_id.warehouse_id.id

            # Inherit station from parent
            if self.parent_location_id.station_id:
                self.station_id = self.parent_location_id.station_id.id

            # If parent has no warehouse, warn user
            if not self.parent_location_id.warehouse_id:
                return {
                    'warning': {
                        'title': 'No Warehouse',
                        'message': 'The parent location has no warehouse assigned. Please set one manually.'
                    }
                }

            # If parent has no station, warn user
            if not self.parent_location_id.station_id:
                return {
                    'warning': {
                        'title': 'No Station',
                        'message': 'The parent location has no station assigned. Please set one manually.'
                    }
                }

    # ★ Filter station based on parent location
    @api.onchange('parent_location_id')
    def _onchange_parent_station_domain(self):
        if self.parent_location_id and self.parent_location_id.station_id:
            # When parent has a station, restrict station selection to parent's station
            self.station_id = self.parent_location_id.station_id.id
            return {
                'domain': {
                    'station_id': [('id', '=', self.parent_location_id.station_id.id)]
                }
            }
        else:
            # If no parent, show all stations
            return {
                'domain': {
                    'station_id': []
                }
            }

    # ★ REMOVED: unique_name constraint - name can be duplicated under different parents
    _sql_constraints = [
        ('unique_code', 'unique(code)', 'Location code must be unique!')
    ]

    @api.constrains('name', 'code')
    def _check_unique(self):
        for record in self:
            # Only check code uniqueness (name can be duplicated under different parents)
            if self.search_count([('code', '=', record.code), ('id', '!=', record.id)]) > 0:
                raise ValidationError('Location code must be unique!')

    # ★ Prevent circular parent-child relationships
    @api.constrains('parent_location_id')
    def _check_parent_location(self):
        for record in self:
            if record.parent_location_id:
                if record.parent_location_id.id == record.id:
                    raise ValidationError('A location cannot be its own parent!')

                current = record.parent_location_id
                while current:
                    if current.id == record.id:
                        raise ValidationError('Circular parent-child relationship detected!')
                    current = current.parent_location_id

    @api.constrains('parent_location_id', 'station_id')
    def _check_station_consistency(self):
        for record in self:
            if record.parent_location_id and record.parent_location_id.station_id:
                if record.station_id and record.station_id.id != record.parent_location_id.station_id.id:
                    raise ValidationError(
                        f'Station "{record.station_id.name}" does not match parent location\'s station "{record.parent_location_id.station_id.name}".'
                    )

    @api.constrains('is_admin_office')
    def _check_admin_office_unique(self):
        admin_offices = self.search([('is_admin_office', '=', True)])
        if len(admin_offices) > 1:
            raise ValidationError(
                "Only one location can be marked as Admin Office!\n"
                f"Currently marked: {', '.join(admin_offices.mapped('name'))}"
            )