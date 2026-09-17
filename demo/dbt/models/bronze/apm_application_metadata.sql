-- Reference data as landed.
select * from read_csv('{{ var("data_dir") }}/reference/apm_applications.csv', header = true)
