"""Shop format: customer area, product brand/HSN, cash vs GST bills, app settings

Revision ID: 0002_shop_format
Revises: f93ffde0bc76
"""
import sqlalchemy as sa
from alembic import op

revision = "0002_shop_format"
down_revision = "f93ffde0bc76"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("customers") as b:
        b.add_column(sa.Column("area", sa.String(80), nullable=False, server_default=""))
        b.create_index("ix_customers_area", ["area"])
    with op.batch_alter_table("products") as b:
        b.add_column(sa.Column("brand", sa.String(80), nullable=False, server_default=""))
        b.add_column(sa.Column("hsn", sa.String(20), nullable=False, server_default=""))
    with op.batch_alter_table("invoices") as b:
        b.add_column(sa.Column("tax_mode", sa.String(10), nullable=False, server_default="BILL"))
        b.create_index("ix_invoices_tax_mode", ["tax_mode"])
    with op.batch_alter_table("invoice_lines") as b:
        b.add_column(sa.Column("brand", sa.String(80), nullable=False, server_default=""))
        b.add_column(sa.Column("hsn", sa.String(20), nullable=False, server_default=""))
    op.create_table("app_settings", sa.Column("key", sa.String(60), primary_key=True),
                    sa.Column("value", sa.Text(), nullable=False))


def downgrade():
    op.drop_table("app_settings")
    with op.batch_alter_table("invoice_lines") as b:
        b.drop_column("hsn")
        b.drop_column("brand")
    with op.batch_alter_table("invoices") as b:
        b.drop_index("ix_invoices_tax_mode")
        b.drop_column("tax_mode")
    with op.batch_alter_table("products") as b:
        b.drop_column("hsn")
        b.drop_column("brand")
    with op.batch_alter_table("customers") as b:
        b.drop_index("ix_customers_area")
        b.drop_column("area")
