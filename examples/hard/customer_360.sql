-- Customer 360: revenue, marketing engagement and web activity rolled up per customer.
-- Intentionally long, nested, with a reusable monthly_orders block.
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

order_revenue as (
    select
        mo.customer_id,
        sum(mo.total_amount)              as revenue,
        sum(mo.order_count)               as orders,
        max(mo.order_month)               as last_active_month
    from monthly_orders mo
    group by mo.customer_id
),

payment_summary as (
    select
        o.customer_id,
        sum(p.amount)                     as paid_amount,
        count(distinct p.payment_id)      as payments,
        count(distinct p.method)          as payment_methods
    from finance.payments p
    join sales.orders o on p.order_id = o.order_id
    group by o.customer_id
),

campaign_engagement as (
    select
        cc.customer_id,
        count(distinct cc.campaign_id)    as campaigns_clicked,
        count(*)                          as total_clicks,
        min(cc.click_date)                as first_click,
        max(cc.click_date)                as last_click
    from marketing.campaign_clicks cc
    join marketing.campaigns ca on cc.campaign_id = ca.campaign_id
    where ca.channel in ('email', 'paid_search')
    group by cc.customer_id
),

web_activity as (
    select
        e.customer_id,
        count(*)                          as events,
        count(distinct e.session_id)      as sessions,
        count(distinct e.event_type)      as event_types
    from web.events e
    where e.event_time >= dateadd('day', -90, current_date)
    group by e.customer_id
),

enriched_customers as (
    select
        c.customer_id,
        c.name,
        c.email,
        c.segment_id,
        c.region_id,
        s.segment_name,
        r.region_name,
        r.country
    from core.customers c
    left join core.segments s on c.segment_id = s.segment_id
    left join core.regions  r on c.region_id  = r.region_id
    where c.status = 'active'
)

select
    ec.customer_id,
    ec.name,
    ec.email,
    ec.segment_name,
    ec.region_name,
    ec.country,
    coalesce(orev.revenue, 0)             as revenue,
    coalesce(orev.orders, 0)              as orders,
    orev.last_active_month,
    coalesce(ps.paid_amount, 0)           as paid_amount,
    coalesce(ps.payment_methods, 0)       as payment_methods,
    coalesce(ce.campaigns_clicked, 0)     as campaigns_clicked,
    coalesce(ce.total_clicks, 0)          as total_clicks,
    coalesce(wa.events, 0)                as web_events,
    coalesce(wa.sessions, 0)              as web_sessions
from enriched_customers ec
left join order_revenue      orev on ec.customer_id = orev.customer_id
left join payment_summary    ps   on ec.customer_id = ps.customer_id
left join campaign_engagement ce  on ec.customer_id = ce.customer_id
left join web_activity       wa   on ec.customer_id = wa.customer_id
where coalesce(orev.revenue, 0) > 0
   or coalesce(ce.total_clicks, 0) > 0
order by revenue desc;
