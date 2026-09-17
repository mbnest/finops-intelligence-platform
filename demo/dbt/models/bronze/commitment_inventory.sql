-- Reference data as landed.
select * from read_csv('{{ var("data_dir") }}/reference/commitments.csv', header = true)
