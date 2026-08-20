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

    display_name = fields.Char(
        string='Display Name',
        compute='_compute_display_name',
        store=True,
    )

    @api.depends('name', 'station_id', 'station_id.name', 'warehouse_id', 'warehouse_id.name')
    def _compute_display_name(self):
        for record in self:
            parts = []
            if record.warehouse_id:
                parts.append(record.warehouse_id.name)
            if record.station_id:
                parts.append(record.station_id.name)
            if record.name:
                parts.append(record.name)
            record.display_name = ' / '.join(parts) if parts else record.name


    _sql_constraints = [
        ('unique_code', 'unique(code)', 'Location code must be unique!'),
        ('unique_name', 'unique(name)', 'Location name must be unique!')
    ]

    @api.constrains('name', 'code')
    def _check_unique(self):
        for record in self:
            if self.search_count([('name', '=', record.name), ('id', '!=', record.id)]) > 0:
                raise ValidationError('Location name must be unique!')