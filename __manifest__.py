{
    'name': 'UNA Inventory Management',
    'version': '17.0.1.0.0',
    'category': 'Inventory',
    'summary': 'UNA Inventory & Asset Management',
    'description': """
        UNA Inventory & Asset Management System
        - Asset tracking with serial numbers
        - Consumable management
        - Requisition workflow
        - Stock reconciliation
    """,
    'author': 'UNA',
    'depends': [
        'base',
        'mail',
        'hr',
        'uom',
        'stock',
        'purchase',
        'portal',
        'una_hr_employee',
        'una_hr_portal_bridge',
    ],
    'data': [
        'security/una_security.xml',
        'security/ir.model.access.csv',
        'data/una_location_data.xml',
        'data/una_sequence_data.xml',
        'data/una_cron_jobs.xml',
        'data/una_email_templates.xml',
        'data/uom_data.xml',
        'views/una_product_views.xml',
        'views/una_location_views.xml',
        'views/una_warehouse_views.xml',
        'views/una_asset_views.xml',
        'views/una_requisition_views.xml',
        'views/portal_templates.xml',
        'views/una_inventory_views.xml',
        'views/una_stock_move_views.xml',
        'views/una_stock_count_views.xml',
        'views/una_report_dashboard_views.xml',
        'report/una_report_dashboard_template.xml',
        'views/menu_views.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}