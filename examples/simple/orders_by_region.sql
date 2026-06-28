select
    r.region_name,
    count(*)        as order_count,
    sum(o.amount)   as total_amount
from sales.orders o
join core.regions r on o.region_id = r.region_id
where o.status = 'completed'
group by r.region_name
order by total_amount desc;
