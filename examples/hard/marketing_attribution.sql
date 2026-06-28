-- Marketing attribution. Includes a NEAR-DUPLICATE of monthly_orders
-- (same tables + output columns, different filter/logic) to exercise
-- structural overlap detection.
with monthly_orders as (
    select
        o.customer_id,
        date_trunc('month', o.order_date) as order_month,
        sum(o.amount)                     as total_amount,
        count(distinct o.order_id)        as order_count
    from sales.orders o
    where o.status in ('completed', 'shipped')
      and o.amount > 0
    group by o.customer_id, date_trunc('month', o.order_date)
),

clicks_by_channel as (
    select
        cc.customer_id,
        ca.channel,
        date_trunc('month', cc.click_date) as click_month,
        count(*)                           as clicks
    from marketing.campaign_clicks cc
    join marketing.campaigns ca on cc.campaign_id = ca.campaign_id
    group by cc.customer_id, ca.channel, date_trunc('month', cc.click_date)
),

attributed as (
    select
        mo.customer_id,
        mo.order_month,
        cbc.channel,
        mo.total_amount,
        mo.order_count,
        cbc.clicks
    from monthly_orders mo
    left join clicks_by_channel cbc
        on mo.customer_id = cbc.customer_id
       and mo.order_month = cbc.click_month
),

segment_lookup as (
    select
        c.customer_id,
        c.segment_id,
        s.segment_name
    from core.customers c
    join core.segments s on c.segment_id = s.segment_id
)

select
    a.channel,
    sl.segment_name,
    a.order_month,
    sum(a.total_amount) as revenue,
    sum(a.order_count)  as orders,
    sum(a.clicks)       as clicks
from attributed a
join segment_lookup sl on a.customer_id = sl.customer_id
group by a.channel, sl.segment_name, a.order_month
order by revenue desc;
