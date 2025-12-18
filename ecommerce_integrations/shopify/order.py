import json
from typing import Literal, Optional
from collections import OrderedDict
import frappe
from frappe import _
from frappe.contacts.doctype.address.address import get_address_display
from frappe.utils import cint, cstr, flt, get_datetime, getdate, nowdate
from shopify.collection import PaginatedIterator
from shopify.resources import Order

from ecommerce_integrations.shopify.connection import temp_shopify_session
from ecommerce_integrations.shopify.constants import (
	EVENT_MAPPER,
	ORDER_ID_FIELD,
	ORDER_ITEM_DISCOUNT_FIELD,
	ORDER_NUMBER_FIELD,
	ORDER_STATUS_FIELD,
	SETTING_DOCTYPE,
)
from ecommerce_integrations.shopify.customer import ShopifyCustomer
from ecommerce_integrations.shopify.product import create_items_if_not_exist, get_item_code
from ecommerce_integrations.shopify.utils import create_shopify_log
from ecommerce_integrations.utils.price_list import get_dummy_price_list
from ecommerce_integrations.utils.taxation import get_dummy_tax_category

DEFAULT_TAX_FIELDS = {
	"sales_tax": "default_sales_tax_account",
	"shipping": "default_shipping_charges_account",
}


def sync_sales_order(payload, request_id=None):
	order = payload
	frappe.set_user("Administrator")
	frappe.flags.request_id = request_id

	if frappe.db.get_value("Sales Order", filters={ORDER_ID_FIELD: cstr(order["id"])}):
		create_shopify_log(status="Invalid", message="Sales order already exists, not synced")
		return
	try:
		shopify_customer = order.get("customer") if order.get("customer") is not None else {}
		shopify_customer["billing_address"] = order.get("billing_address", "")
		shopify_customer["shipping_address"] = order.get("shipping_address", "")
		customer_id = shopify_customer.get("id")
		if customer_id:
			shopify_platform_customer = ShopifyCustomer(customer_id=customer_id)
			if not shopify_platform_customer.is_synced():
				shopify_platform_customer.sync_customer(customer=shopify_customer)
			else:
				shopify_platform_customer.update_existing_addresses(shopify_customer)

		create_items_if_not_exist(order)

		setting = frappe.get_doc(SETTING_DOCTYPE)
		create_order(order, setting)
	except Exception as e:
		create_shopify_log(status="Error", exception=e, rollback=True)
	else:
		create_shopify_log(status="Success")


def create_order(order, setting, company=None):
	# local import to avoid circular dependencies
	from ecommerce_integrations.shopify.fulfillment import create_delivery_note
	from ecommerce_integrations.shopify.invoice import create_sales_invoice

	so = create_sales_order(order, setting, company)
	if so:
		if order.get("financial_status") == "paid":
			create_sales_invoice(order, setting, so)

		if order.get("fulfillments"):
			create_delivery_note(order, setting, so)


def create_sales_order(shopify_order, setting, company=None):
	from ecommerce_integrations.shopify.customer import (
		get_shopify_platform_customer_address_doc as platform_customer_address_doc,
	)

	customer = setting.default_customer

	billing_address = None
	billing_address_display = None
	shipping_address = None
	shipping_address_display = None
	if shopify_order.get("customer", {}):
		if customer_id := shopify_order.get("customer", {}).get("id"):
			if billing_address := platform_customer_address_doc(customer_id, address_type="Billing"):
				billing_address_display = get_address_display(billing_address.as_dict())
			if shipping_address := platform_customer_address_doc(customer_id, address_type="Shipping"):
				shipping_address_display = get_address_display(shipping_address.as_dict())

	so = frappe.db.get_value("Sales Order", {ORDER_ID_FIELD: shopify_order.get("id")}, "name")
	# Create customer fullname
	# if shopify_order.get("customer"):
	# 	first_name = shopify_order.get("customer").get("first_name", "")
	# 	last_name = shopify_order.get("customer").get("last_name", "")
	# 	shopify_customer_full_name = first_name + " " + last_name
	# else:
	# 	shopify_customer_full_name = ""

	# Create billing address with below sample data
	# if shopify_order.get("billing_address"):
	# 	address_line_1 = shopify_order.get("billing_address").get("address1", "")
	# 	address_line_2 = shopify_order.get("billing_address").get("address2", "")
	# 	city = shopify_order.get("billing_address").get("city", "")
	# 	zip_code = shopify_order.get("billing_address").get("zip", "")
	# 	province = shopify_order.get("billing_address").get("province", "")
	# 	country = shopify_order.get("billing_address").get("country", "")
	# 	phone = shopify_order.get("billing_address").get("phone", "")
	# 	shopify_billing_address = address_line_1 + ",\n" + address_line_2 + ",\n" + city + ",\n" + zip_code + ",\n" + province + ",\n" + country + ",\n" + phone
	# else:
	# 	shopify_billing_address = ""
	# if shopify_order.get("billing_address"):
	# 	billing_address = shopify_order.get("billing_address")
	# 	address_line_1 = str(billing_address.get("address1", "") or "")
	# 	address_line_2 = str(billing_address.get("address2", "") or "")
	# 	city = str(billing_address.get("city", "") or "")
	# 	zip_code = str(billing_address.get("zip", "") or "")
	# 	province = str(billing_address.get("province", "") or "")
	# 	country = str(billing_address.get("country", "") or "")
	# 	phone = str(billing_address.get("phone", "") or "")

		# Join non-empty parts with a newline
		# shopify_billing_address = ",\n".join(
		# 	filter(None, [address_line_1, address_line_2, city, zip_code, province, country, phone])
		# )
	# else:
	# 	shopify_billing_address = ""

	# Create shipping address with below sample data
	# if shopify_order.get("shipping_address"):
	# 	address_line_1 = shopify_order.get("shipping_address").get("address1", "")
	# 	address_line_2 = shopify_order.get("shipping_address").get("address2", "")
	# 	city = shopify_order.get("shipping_address").get("city", "")
	# 	zip_code = shopify_order.get("shipping_address").get("zip", "")
	# 	province = shopify_order.get("shipping_address").get("province", "")
	# 	country = shopify_order.get("shipping_address").get("country", "")
	# 	phone = shopify_order.get("shipping_address").get("phone", "")
	# 	shopify_shipping_address = address_line_1 + ",\n" + address_line_2 + ",\n" + city + ",\n" + zip_code + ",\n" + province + ",\n" + country + ",\n" + phone
	# else:
	# 	shopify_shipping_address = ""
	# if shopify_order.get("shipping_address"):
	# 	shipping_address = shopify_order.get("shipping_address")
	# 	address_line_1 = shipping_address.get("address1", "") or ""
	# 	address_line_2 = shipping_address.get("address2", "") or ""
	# 	city = shipping_address.get("city", "") or ""
	# 	zip_code = shipping_address.get("zip", "") or ""
	# 	province = shipping_address.get("province", "") or ""
	# 	country = shipping_address.get("country", "") or ""
	# 	phone = shipping_address.get("phone", "") or ""

		# Construct the shipping address string
		# address_parts = [address_line_1, address_line_2, city, zip_code, province, country, phone]
		# address_parts = [part for part in address_parts if part]  # Remove empty or None values
		# shopify_shipping_address = ",\n".join(address_parts)
	# else:
	# 	shopify_shipping_address = ""

	if not so:
		items = get_order_items(
			shopify_order.get("line_items"),
			setting,
			getdate(shopify_order.get("created_at")),
			taxes_inclusive=shopify_order.get("taxes_included"),
		)

		if not items:
			message = (
				"Following items exists in the shopify order but relevant records were"
				" not found in the shopify Product master"
			)
			product_not_exists = []  # TODO: fix missing items
			message += "\n" + ", ".join(product_not_exists)

			create_shopify_log(status="Error", exception=message, rollback=True)

			return ""
		
		selling_price_list = frappe.db.get_single_value("Selling Settings", "selling_price_list")
		if not selling_price_list:	
			selling_price_list = get_dummy_price_list()
		
		taxes = get_order_taxes(shopify_order, setting, items)
		so = frappe.get_doc(
			{
				"doctype": "Sales Order",
				"naming_series": setting.sales_order_series or "SO-Shopify-",
				ORDER_ID_FIELD: str(shopify_order.get("id")),
				ORDER_NUMBER_FIELD: shopify_order.get("name"),
				"customer": customer,
				# "custom_shopify_customer_name": shopify_customer_full_name,
				# "custom_shopify_customer_billing_address": billing_address_display,
				# "custom_shopify_customer_shipping_address": shipping_address_display,
				"transaction_date": getdate(shopify_order.get("created_at")) or nowdate(),
				"delivery_date": getdate(shopify_order.get("created_at")) or nowdate(),
				"company": setting.company,
				"selling_price_list": selling_price_list,
				"ignore_pricing_rule": 0,
				"items": items,
				"taxes": taxes,
				"tax_category": None,
				"shopify_customer_id": customer_id,
				"customer_address": billing_address.name if billing_address else None,
				"shopify_billing_address": billing_address.name if billing_address else None,
				"shopify_billing_address_display": billing_address_display,
				"shipping_address_name": shipping_address.name if shipping_address else None,
				"shopify_shipping_address": shipping_address.name if shipping_address else None,
				"shopify_shipping_address_display": shipping_address_display,
			}
		)

		if company:
			so.update({"company": company, "status": "Draft"})
		so.flags.ignore_mandatory = True
		so.flags.shopiy_order_json = json.dumps(shopify_order)
		so.save(ignore_permissions=True)
		# so.submit()

		if shopify_order.get("note"):
			so.add_comment(text=f"Order Note: {shopify_order.get('note')}")

	else:
		so = frappe.get_doc("Sales Order", so)

	return so


def get_order_items(order_items, setting, delivery_date, taxes_inclusive):
	items = []
	all_product_exists = True
	product_not_exists = []

	for shopify_item in order_items:
		if not shopify_item.get("product_exists"):
			all_product_exists = False
			product_not_exists.append(
				{"title": shopify_item.get("title"), ORDER_ID_FIELD: shopify_item.get("id")}
			)
			continue

		if all_product_exists:
			item_code = get_item_code(shopify_item)
			items.append(
				{
					"item_code": item_code,
					"item_name": shopify_item.get("name"),
					"rate": _get_item_price(shopify_item, taxes_inclusive),
					"delivery_date": delivery_date,
					"qty": shopify_item.get("quantity"),
					"stock_uom": shopify_item.get("uom") or "Nos",
					"warehouse": setting.warehouse,
					ORDER_ITEM_DISCOUNT_FIELD: (
						_get_total_discount(shopify_item) / cint(shopify_item.get("quantity"))
					),
				}
			)
		else:
			items = []

	return items

def _get_item_price(line_item, taxes_inclusive: bool) -> float:
	"""
	Calculate the net item price (excluding tax) from Shopify line item.
	
	For tax-inclusive pricing:
	- Shopify price includes tax
	- We need to extract the base price by removing tax component
	
	For tax-exclusive pricing:
	- Shopify price is already the base price
	- Just apply discounts
	"""
	price = flt(line_item.get("price"))
	qty = flt(line_item.get("quantity")) or 1
	
	# Apply line item discount
	total_discount = flt(line_item.get("total_discount") or 0)
	discount_per_qty = total_discount / qty
	discounted_price = price - discount_per_qty
	
	# Get tax lines
	tax_lines = line_item.get("tax_lines") or []
	
	# If tax-exclusive or no taxes, return discounted price as-is
	if not taxes_inclusive or not tax_lines:
		return discounted_price
	
	# Tax-inclusive: need to extract base price
	# Calculate total tax rate from all tax lines
	total_tax_rate = sum(flt(t.get("rate")) for t in tax_lines) * 100
	
	if total_tax_rate > 0:
		# Formula: base_price = gross_price / (1 + tax_rate/100)
		# Or: base_price = gross_price * 100 / (100 + tax_rate)
		base_price = discounted_price * 100 / (100 + total_tax_rate)
		return flt(base_price)
	
	# Fallback: if no valid tax rate found, try calculating from tax amounts
	total_tax_amount = sum(flt(t.get("price")) for t in tax_lines) / qty
	base_price = discounted_price - total_tax_amount
	
	# Safety check: base price should never be negative
	if base_price < 0:
		frappe.log_error(
			f"Negative base price calculated for item {line_item.get('sku')}: "
			f"Price={price}, Discount={discount_per_qty}, Tax={total_tax_amount}",
			"Shopify Item Price Calculation Error"
		)
		# Fallback to discounted price
		return discounted_price
	frappe.log_error("Shopify Item Price Calculation",f"Item base price calculated for item {line_item.get('sku')}: "
			f"Price={price}, Discount={discount_per_qty}, Tax={total_tax_amount}")
	return flt(base_price)


def _get_total_discount(line_item) -> float:
	discount_allocations = line_item.get("discount_allocations") or []
	return sum(flt(discount.get("amount")) for discount in discount_allocations)


def get_order_taxes(shopify_order, setting, items):
	try:
		taxes = []
		taxes_inclusive = shopify_order.get("taxes_included", False)
		line_items = shopify_order.get("line_items", [])

		# Collect taxes from line items
		tax_map = {}  # {tax_title: {rate, account_head, items: {}, total_amount}}
		
		# Check if Shopify has aggregated all taxes in first item
		# This happens when first item has tax_lines but others don't
		first_item_has_taxes = bool(line_items and line_items[0].get("tax_lines"))
		other_items_have_taxes = any(
			bool(item.get("tax_lines")) 
			for item in line_items[1:] if item.get("taxable", True)
		)
		
		# If first item has taxes but others don't, taxes are aggregated
		taxes_are_aggregated = first_item_has_taxes and not other_items_have_taxes
		
		if taxes_are_aggregated:
			# Use order-level tax_lines and distribute proportionally to ALL items
			order_tax_lines = shopify_order.get("tax_lines", [])
			
			for line_item in line_items:
				item_code = get_item_code(line_item)
				
				# Skip non-taxable items
				if not line_item.get("taxable", True):
					continue
				
				# Get item quantity
				item_qty = flt(line_item.get("quantity", 1))
				
				# Get discount allocated to this item
				discount_allocations = line_item.get("discount_allocations", [])
				item_discount = sum(flt(d.get("amount")) for d in discount_allocations)
				
				# Get net price per unit (after discount, excluding tax if inclusive)
				# But for tax calculation, we need gross amount after discount
				item_price = flt(line_item.get("price"))
				net_item_amount = (item_price * item_qty) - item_discount
				
				# Apply each order-level tax to this item
				for order_tax in order_tax_lines:
					tax_title = order_tax.get("title")
					shopify_tax_rate = flt(order_tax.get("rate")) * 100
					
					# Calculate tax for this item
					if taxes_inclusive:
						# Tax included: extract tax from gross amount after discount
						item_tax_amount = net_item_amount * shopify_tax_rate / (100 + shopify_tax_rate)
					else:
						# Tax exclusive: calculate on net amount after discount
						item_tax_amount = net_item_amount * shopify_tax_rate / 100
					
					if tax_title not in tax_map:
						account_head, charge_type, order_sequence = get_tax_account_head(
							order_tax, charge_type="sales_tax"
						)
						# Get display rate: IGST=18, CGST=9, SGST=9
						display_rate = get_display_tax_rate(tax_title) or shopify_tax_rate
						
						tax_map[tax_title] = {
							"tax_title": tax_title,
							"rate": display_rate,
							"shopify_rate": shopify_tax_rate,
							"account_head": account_head,
							"charge_type": charge_type or "On Previous Row Total",
							"order_sequence": order_sequence,
							"description": (
								get_tax_account_description(order_tax)
								or f"{tax_title} @ {display_rate:.2f}%"
							),
							"total_tax_amount": 0,
							"items": {}
						}
					
					# Add this item's tax
					tax_map[tax_title]["items"][item_code] = [shopify_tax_rate, item_tax_amount]
					tax_map[tax_title]["total_tax_amount"] += item_tax_amount
		else:
			# Normal flow: process taxes from line items as before
			# First pass: collect explicit taxes from line items
			items_with_taxes = set()
			for line_item in line_items:
				item_code = get_item_code(line_item)
				tax_lines = line_item.get("tax_lines", [])
				
				if tax_lines:
					items_with_taxes.add(item_code)
					for tax in tax_lines:
						tax_title = tax.get("title")
						shopify_tax_rate = flt(tax.get("rate")) * 100  # Shopify's rate (e.g., 5%)
						tax_amount = flt(tax.get("price"))
						
						if tax_title not in tax_map:
							account_head, charge_type, order_sequence = get_tax_account_head(
								tax, charge_type="sales_tax"
							)
							# Get display rate: IGST=18, CGST=9, SGST=9
							display_rate = get_display_tax_rate(tax_title) or shopify_tax_rate
							
							tax_map[tax_title] = {
								"tax_title": tax_title,
								"rate": display_rate,  # Fixed rate (18 for IGST, 9 for CGST/SGST)
								"shopify_rate": shopify_tax_rate,  # Shopify's actual rate (e.g., 5%)
								"account_head": account_head,
								"charge_type": charge_type or "On Previous Row Total",
								"order_sequence": order_sequence,
								"description": (
									get_tax_account_description(tax)
									or f"{tax.get('title')} @ {display_rate:.2f}%"
								),
								"total_tax_amount": 0,
								"items": {}
							}
						
						# Add item's tax with Shopify's rate
						tax_map[tax_title]["items"][item_code] = [shopify_tax_rate, tax_amount]
						tax_map[tax_title]["total_tax_amount"] += tax_amount
		
		# Second pass: handle items without explicit tax_lines (only in normal flow)
		if not taxes_are_aggregated:
			order_tax_lines = shopify_order.get("tax_lines", [])
			for line_item in line_items:
				item_code = get_item_code(line_item)
				
				# Skip items that already have taxes
				if item_code in items_with_taxes:
					continue
				
				# Skip non-taxable items
				if not line_item.get("taxable", True):
					continue
				
				# Get item quantity
				item_qty = flt(line_item.get("quantity", 1))
				
				# Get discount allocated to this item
				discount_allocations = line_item.get("discount_allocations", [])
				item_discount = sum(flt(d.get("amount")) for d in discount_allocations)
				
				# Get net price per unit (after discount, excluding tax if inclusive)
				# For tax calculation, we need gross amount after discount
				item_price = flt(line_item.get("price"))
				net_item_amount = (item_price * item_qty) - item_discount
				
				# Apply each order-level tax to this item
				for order_tax in order_tax_lines:
					tax_title = order_tax.get("title")
					shopify_tax_rate = flt(order_tax.get("rate")) * 100
					
					# Calculate tax for this item
					if taxes_inclusive:
						# Tax included: extract tax from gross amount after discount
						item_tax_amount = net_item_amount * shopify_tax_rate / (100 + shopify_tax_rate)
					else:
						# Tax exclusive: calculate on net amount after discount
						item_tax_amount = net_item_amount * shopify_tax_rate / 100
					
					if tax_title not in tax_map:
						account_head, charge_type, order_sequence = get_tax_account_head(
							order_tax, charge_type="sales_tax"
						)
						# Get display rate: IGST=18, CGST=9, SGST=9
						display_rate = get_display_tax_rate(tax_title) or shopify_tax_rate
						
						tax_map[tax_title] = {
							"tax_title": tax_title,
							"rate": display_rate,  # Fixed rate (18 for IGST, 9 for CGST/SGST)
							"shopify_rate": shopify_tax_rate,  # Shopify's actual rate
							"account_head": account_head,
							"charge_type": charge_type or "On Previous Row Total",
							"order_sequence": order_sequence,
							"description": (
								get_tax_account_description(order_tax)
								or f"{tax_title} @ {display_rate:.2f}%"
							),
							"total_tax_amount": 0,
							"items": {}
						}
					
					# Add this item's tax with Shopify's rate
					tax_map[tax_title]["items"][item_code] = [shopify_tax_rate, item_tax_amount]
					tax_map[tax_title]["total_tax_amount"] += item_tax_amount

		# Convert tax_map to taxes list
		for tax_data in tax_map.values():
			# For tax-inclusive, use display rate in item_wise_tax_detail
			# For tax-exclusive, use shopify rate
			rate_for_items = tax_data["rate"] if taxes_inclusive else tax_data["shopify_rate"]
			
			# Adjust item_wise_tax_detail to use correct rate
			adjusted_items = {}
			for item_code, (shopify_rate, tax_amount) in tax_data["items"].items():
				adjusted_items[item_code] = [rate_for_items, tax_amount]
			
			taxes.append({
				"charge_type": tax_data["charge_type"],
				"account_head": tax_data["account_head"],
				"description": tax_data["description"],
				"rate": tax_data["rate"],
				"tax_amount": tax_data["total_tax_amount"],
				"cost_center": setting.cost_center,
				"order_sequence": tax_data["order_sequence"],
				"item_wise_tax_detail": adjusted_items,
				"included_in_print_rate": 1 if taxes_inclusive else 0,
				"dont_recompute_tax": 1,
			})

		# Add shipping taxes
		if shopify_order.get("shipping_lines"):
			update_taxes_with_shipping_lines(
				taxes,
				shopify_order["shipping_lines"],
				setting,
				items,
				taxes_inclusive,
			)

		# Consolidate if needed
		if cint(setting.consolidate_taxes):
			taxes = consolidate_order_taxes(taxes)

		# Sort by order_sequence
		taxes = sorted(taxes, key=lambda x: x.get("order_sequence", 0))

		# Apply ERPNext tax row rules
		for idx, row in enumerate(taxes, start=1):
			row["idx"] = idx
			
			# First row is always "Actual" with no row_id
			if idx == 1:
				row["charge_type"] = "Actual"
				row["row_id"] = None
			else:
				# Subsequent rows are "On Previous Row Total" referencing row 1
				if row["charge_type"] != "Actual":
					row["charge_type"] = "On Previous Row Total"
				row["row_id"] = "1"
			
			# Convert item_wise_tax_detail to JSON
			tax_detail = row.get("item_wise_tax_detail")
			if isinstance(tax_detail, dict):
				row["item_wise_tax_detail"] = json.dumps(tax_detail)
		frappe.log_error("Taxes Calcualtion",taxes)
		return taxes

	except Exception:
		frappe.log_error(frappe.get_traceback(), "Shopify Order Tax Sync Failed")
		return []


def consolidate_order_taxes(taxes):
	"""Consolidate taxes by account_head"""
	tax_account_wise_data = {}
	
	for tax in taxes:
		account_head = tax["account_head"]
		
		if account_head not in tax_account_wise_data:
			tax_account_wise_data[account_head] = {
				"charge_type": tax.get("charge_type", "On Previous Row Total"),
				"account_head": account_head,
				"description": tax.get("description"),
				"cost_center": tax.get("cost_center"),
				"rate": flt(tax.get("rate")),
				"order_sequence": tax.get("order_sequence", 0),
				"included_in_print_rate": tax.get("included_in_print_rate", 0),
				"dont_recompute_tax": 1,
				"tax_amount": 0,
				"item_wise_tax_detail": {},
			}
		
		# Accumulate tax amount
		tax_account_wise_data[account_head]["tax_amount"] += flt(tax.get("tax_amount"))
		
		# Merge item_wise_tax_detail
		if tax.get("item_wise_tax_detail"):
			item_wise = tax["item_wise_tax_detail"]
			existing_detail = tax_account_wise_data[account_head]["item_wise_tax_detail"]
			
			for item_code, tax_detail in item_wise.items():
				if item_code in existing_detail:
					# Sum the tax amounts for same item
					existing_detail[item_code] = [
						tax_detail[0],  # rate stays same
						existing_detail[item_code][1] + tax_detail[1]  # sum amounts
					]
				else:
					existing_detail[item_code] = tax_detail
	
	return list(tax_account_wise_data.values())


def get_tax_account_head(tax, charge_type: Optional[Literal["shipping", "sales_tax"]] = None):
	"""Get tax account head, charge type, and order sequence"""
	tax_title = str(tax.get("title"))

	tax_account_data = frappe.db.get_value(
		"Shopify Tax Account",
		{"parent": SETTING_DOCTYPE, "shopify_tax": tax_title},
		["tax_account", "charge_type", "order_sequence"],
		as_dict=True,
	)

	if tax_account_data:
		tax_account = tax_account_data.tax_account
		chargeable_type = tax_account_data.charge_type or "On Previous Row Total"
		order_sequence = tax_account_data.order_sequence or 0
	else:
		tax_account = None
		chargeable_type = "On Previous Row Total"
		order_sequence = 0

	# Fallback to default tax account
	if not tax_account and charge_type:
		tax_account = frappe.db.get_single_value(SETTING_DOCTYPE, DEFAULT_TAX_FIELDS[charge_type])

	if not tax_account:
		frappe.throw(_("Tax Account not specified for Shopify Tax {0}").format(tax.get("title")))

	return tax_account, chargeable_type, order_sequence


def get_display_tax_rate(tax_title):
	"""
	Get the display tax rate for ERPNext based on tax title.
	IGST = 18%, CGST = 9%, SGST = 9%
	"""
	tax_title_upper = tax_title.upper()
	
	if "IGST" in tax_title_upper:
		return 18.0
	elif "CGST" in tax_title_upper:
		return 9.0
	elif "SGST" in tax_title_upper:
		return 9.0
	else:
		# For other taxes, return None to use Shopify's rate
		return None


def get_tax_account_description(tax):
	"""Get custom tax description if configured"""
	tax_title = tax.get("title")

	tax_description = frappe.db.get_value(
		"Shopify Tax Account",
		{"parent": SETTING_DOCTYPE, "shopify_tax": tax_title},
		"tax_description",
	)
	
	return tax_description


def update_taxes_with_shipping_lines(taxes, shipping_lines, setting, items, taxes_inclusive=False):
	"""
	Add shipping charges and taxes.
	Shipping charge becomes first row (Actual), taxes reference it.
	"""
	shipping_as_item = cint(setting.add_shipping_as_item) and setting.shipping_item

	for shipping_charge in shipping_lines:
		if not shipping_charge.get("price"):
			continue

		# Calculate shipping amount
		shipping_discounts = shipping_charge.get("discount_allocations") or []
		total_discount = sum(flt(d.get("amount")) for d in shipping_discounts)

		shipping_taxes = shipping_charge.get("tax_lines") or []
		total_tax = sum(flt(t.get("price")) for t in shipping_taxes)

		shipping_charge_amount = flt(shipping_charge["price"]) - total_discount

		# Remove tax if inclusive
		if taxes_inclusive:
			shipping_charge_amount -= total_tax

		# Add shipping as item or as charge
		if shipping_as_item:
			items.append({
				"item_code": setting.shipping_item,
				"rate": shipping_charge_amount,
				"delivery_date": items[-1]["delivery_date"] if items else nowdate(),
				"qty": 1,
				"stock_uom": "Nos",
				"warehouse": setting.warehouse,
			})
		else:
			# Add shipping charge (will become first row with "Actual")
			# Always add, even if amount is 0
			account_head, charge_type, order_sequence = get_tax_account_head(
				shipping_charge, charge_type="shipping"
			)
			
			# Shipping charge should have order_sequence=0 to appear first
			taxes.append({
				"charge_type": "Actual",  # Will be enforced as first row
				"account_head": account_head,
				"description": (
					get_tax_account_description(shipping_charge)
					or shipping_charge.get("title")
					or "Shipping Charges"
				),
				"rate": 0.0,
				"tax_amount": shipping_charge_amount,
				"cost_center": setting.cost_center,
				"order_sequence": 0,  # Ensure it appears first
				"item_wise_tax_detail": {},
				"dont_recompute_tax": 0,
			})

		# Add shipping taxes (IGST or SGST+CGST)
		for tax in shipping_taxes:
			account_head, charge_type, order_sequence = get_tax_account_head(
				tax, charge_type="sales_tax"
			)

			shopify_tax_rate = flt(tax.get("rate")) * 100
			tax_title = tax.get("title")
			display_rate = get_display_tax_rate(tax_title) or shopify_tax_rate
			tax_amount = flt(tax.get("price"))

			# Find if this tax already exists in taxes list
			existing_tax = None
			for existing in taxes:
				if existing.get("account_head") == account_head:
					existing_tax = existing
					break
			
			if existing_tax:
				# Add to existing tax entry
				existing_tax["tax_amount"] += tax_amount
				
				# Add to item_wise_tax_detail if shipping_as_item
				if shipping_as_item:
					item_wise = existing_tax.get("item_wise_tax_detail", {})
					# Use display rate (not shopify rate) for tax-inclusive
					rate_to_use = display_rate if taxes_inclusive else shopify_tax_rate
					if setting.shipping_item in item_wise:
						item_wise[setting.shipping_item][1] += tax_amount
					else:
						item_wise[setting.shipping_item] = [rate_to_use, tax_amount]
					existing_tax["item_wise_tax_detail"] = item_wise
			else:
				# Create new tax entry
				# Use display rate (not shopify rate) for tax-inclusive
				rate_for_item_wise = display_rate if taxes_inclusive else shopify_tax_rate
				
				taxes.append({
					"charge_type": charge_type or "On Previous Row Total",
					"account_head": account_head,
					"description": (
						get_tax_account_description(tax)
						or f"{tax.get('title')} @ {display_rate:.2f}%"
					),
					"rate": display_rate,  # Fixed rate (18 for IGST, 9 for CGST/SGST)
					"tax_amount": tax_amount,
					"cost_center": setting.cost_center,
					"order_sequence": order_sequence,
					"item_wise_tax_detail": {
						setting.shipping_item: [rate_for_item_wise, tax_amount]
					} if shipping_as_item else {},
					"included_in_print_rate": 1 if taxes_inclusive else 0,
					"dont_recompute_tax": 1,
				})


def get_sales_order(order_id):
	"""Get ERPNext sales order using shopify order id."""
	sales_order = frappe.db.get_value("Sales Order", filters={ORDER_ID_FIELD: order_id})
	if sales_order:
		return frappe.get_doc("Sales Order", sales_order)


def cancel_order(payload, request_id=None):
	"""Called by order/cancelled event.

	When shopify order is cancelled there could be many different someone handles it.

	Updates document with custom field showing order status.

	IF sales invoice / delivery notes are not generated against an order, then cancel it.
	"""
	frappe.set_user("Administrator")
	frappe.flags.request_id = request_id

	order = payload

	try:
		order_id = order["id"]
		order_status = order["financial_status"]

		sales_order = get_sales_order(order_id)

		if not sales_order:
			create_shopify_log(status="Invalid", message="Sales Order does not exist")
			return

		sales_invoice = frappe.db.get_value("Sales Invoice", filters={ORDER_ID_FIELD: order_id})
		delivery_notes = frappe.db.get_list("Delivery Note", filters={ORDER_ID_FIELD: order_id})

		if sales_invoice:
			frappe.db.set_value("Sales Invoice", sales_invoice, ORDER_STATUS_FIELD, order_status)

		for dn in delivery_notes:
			frappe.db.set_value("Delivery Note", dn.name, ORDER_STATUS_FIELD, order_status)

		if not sales_invoice and not delivery_notes and sales_order.docstatus == 1:
			sales_order.cancel()
		else:
			frappe.db.set_value("Sales Order", sales_order.name, ORDER_STATUS_FIELD, order_status)

	except Exception as e:
		create_shopify_log(status="Error", exception=e)
	else:
		create_shopify_log(status="Success")


@temp_shopify_session
def sync_old_orders():
	try:

		frappe.log_error("Syncing Old Orders")
		shopify_setting = frappe.get_cached_doc(SETTING_DOCTYPE)
		if not cint(shopify_setting.sync_old_orders):
			frappe.log_error("Sync Old Orders is disabled")
			return

		orders = _fetch_old_orders(shopify_setting.old_orders_from, shopify_setting.old_orders_to)

		frappe.log_error(title="Orders Fetched", message=str(orders))

		for order in orders:
			log = create_shopify_log(
				method=EVENT_MAPPER["orders/create"], request_data=json.dumps(order), make_new=True
			)
			sync_sales_order(order, request_id=log.name)

		shopify_setting = frappe.get_doc(SETTING_DOCTYPE)
		shopify_setting.sync_old_orders = 0
		shopify_setting.save()
	except Exception:
		frappe.log_error(title="Sync Old Orders", message=frappe.get_traceback())


def _fetch_old_orders(from_time, to_time):
	"""Fetch all shopify orders in specified range and return an iterator on fetched orders."""
	frappe.log_error(title="Fetching Orders from {} to {}".format(str(from_time), str(to_time)))
	from_time = get_datetime(from_time).astimezone().isoformat()
	to_time = get_datetime(to_time).astimezone().isoformat()

	orders_iterator = PaginatedIterator(
		Order.find(created_at_min=from_time, created_at_max=to_time, limit=250)
	)

	for orders in orders_iterator:
		for order in orders:
			# Using generator instead of fetching all at once is better for
			# avoiding rate limits and reducing resource usage.
			yield order.to_dict()