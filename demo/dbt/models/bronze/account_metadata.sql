-- Reference data as landed.
select * from read_csv('{{ var("data_dir") }}/reference/accounts.csv', header = true)
