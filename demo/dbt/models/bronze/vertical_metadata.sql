-- Reference data as landed.
select * from read_csv('{{ var("data_dir") }}/reference/verticals.csv', header = true)
