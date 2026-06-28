select
    p.product_id,
    p.name              as product_name,
    cat.category_name,
    sum(oi.quantity)            as units_sold,
    sum(oi.quantity * oi.unit_price) as gross_revenue
from sales.order_items oi
join core.products p on oi.product_id = p.product_id
join core.categories cat on p.category_id = cat.category_id
group by p.product_id, p.name, cat.category_name;
