from odoo import models, fields, api
from odoo.exceptions import ValidationError


class UnaWarehouse(models.Model):
    _name = 'una.warehouse'
    _rec_name = 'name'
    _order = 'name'


    name = fields.Char(string='Warehouse Name', required=True)
    code = fields.Char(string='Warehouse Code', required=True, unique=True)
    active= fields.Boolean(string='Active', default=True)


    country = fields.Many2one('res.country', string='Country')
    manager_id = fields.Many2one('hr.employee', string='Manager')

    location_ids = fields.One2many('una.location', 'warehouse_id', string='Locations')
    display_name = fields.Char(string='Display Name', compute='_compute_display_name', store=True,)

    @api.depends('name', 'code')
    def _compute_display_name(self):
        for record in self:
            record.display_name = f"{record.code} - {record.name}" if record.code else record.name

    _sql_constraints = [
        ('unique_code', 'unique(code)', 'Warehouse code must be unique!'),
        ('unique_name', 'unique(name)', 'Warehouse name must be unique!')
    ]

    @api.constrains('name', 'code')
    def _check_unique(self):
        for record in self:
            if self.search_count([('name', '=', record.name), ('id', '!=', record.id)]) > 0:
                raise ValidationError('Warehouse name must be unique!')
