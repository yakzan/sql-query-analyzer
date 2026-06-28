select
    c.customer_id,
    c.name,
    c.email,
    count(o.order_id)   as orders,
    sum(o.amount)       as lifetime_value
from core.customers c
join sales.orders o on c.customer_id = o.customer_id
where c.status = 'active'
group by c.customer_id, c.name, c.email;
