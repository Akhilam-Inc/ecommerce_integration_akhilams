frappe.ui.form.on("Sales Invoice", {
	refresh(frm) {
		if (frm.doc.unicommerce_order_code) {
			frm.add_custom_button(
				__("Open Unicommerce Order"),
				function () {
					frappe.call({
						method:
							"ecommerce_integrations.unicommerce.utils.get_unicommerce_document_url",
						args: {
							code: frm.doc.unicommerce_order_code,
							doctype: frm.doc.doctype,
						},
						callback: function (r) {
							if (!r.exc) {
								window.open(r.message, "_blank");
							}
						},
					});
				},
				__("Unicommerce")
			);
		}

		if (frm.doc.shopify_order_id) {
			frm.add_custom_button(
				__("Update Shopify Fulfillment"),
				function () {
					frappe.call({
						method: "ecommerce_integrations.api.update_shipping_details",
						args: {
							order_id: frm.doc.shopify_order_id,
							tracking_string: frm.doc.custom_eshipz_tracking_number
						},
						callback: function (r) {
							if (!r.exc) {
								frappe.msgprint(__("Shopify Fulfillment Created Successfully"));
								frm.reload_doc();
							}
						}
					});
				},
				__("Shopify")
			);
		}
	},
});
