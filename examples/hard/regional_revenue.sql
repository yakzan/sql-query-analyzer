-- Regional revenue & product mix. Reuses an IDENTICAL monthly_orders block
-- (exact-duplicate overlap) and mixes in product/category dimensions.
-- Contains some unqualified columns and a SELECT * to stress resolution.
with monthly_orders as (
    select
        o.customer_id,
        date_trunc('month', o.order_date) as order_month,
        sum(o.amount)                     as total_amount,
        count(*)                          as order_count
    from sales.orders o
    where o.status = 'completed'
    group by o.customer_id, date_trunc('month', o.order_date)
),

customer_region as (
    select
        c.customer_id,
        c.region_id,
        r.region_name,
        r.country
    from core.customers c
    join core.regions r on c.region_id = r.region_id
),

regional_orders as (
    select
        cr.region_name,
        cr.country,
        mo.order_month,
        sum(mo.total_amount) as revenue,
        sum(mo.order_count)  as orders
    from monthly_orders mo
    join customer_region cr on mo.customer_id = cr.customer_id
    group by cr.region_name, cr.country, mo.order_month
),

item_detail as (
    select
        o.region_id,
        oi.product_id,
        p.category_id,
        cat.category_name,
        sum(oi.quantity)                 as units,
        sum(oi.quantity * oi.unit_price) as item_revenue
    from sales.order_items oi
    join sales.orders   o   on oi.order_id   = o.order_id
    join core.products  p   on oi.product_id = p.product_id
    join core.categories cat on p.category_id = cat.category_id
    where o.status = 'completed'
    group by o.region_id, oi.product_id, p.category_id, cat.category_name
),

category_rollup as (
    select
        region_id,
        category_name,
        sum(units)        as units,
        sum(item_revenue) as item_revenue
    from item_detail
    group by region_id, category_name
)

select *
from regional_orders ro
left join category_rollup crp
    on ro.region_name = crp.category_name
order by ro.revenue desc;
