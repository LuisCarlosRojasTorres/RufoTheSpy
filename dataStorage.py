'''
Este componente é responsável por armazenar os dados coletados de cada device conectado, e para isso ele tem que ter uma função que recebe os dados coletados e armazena em um arquivo .csv, e esse arquivo tem que ser criado caso não exista, e caso exista ele tem que ser atualizado com os novos dados coletados.
O formato do arquivo csv é o mesmo que o arquivo rufo_monitor.py, e o nome do arquivo tem que ser o mesmo que o nome do device conectado, e o arquivo tem que ser salvo na pasta output.
Dependendo do device conectado, o arquivo csv tem que ter o seguinte nome:
- Para o device Primary, o arquivo csv tem que ter o nome de "Primary_<YYMMDD_HHMMSS>.csv"
- Para o device Secondary, o arquivo csv tem que ter o nome de "Secondary_<YYMMDD_HHMMSS>.csv"
- Para o device Tertiary, o arquivo csv tem que ter o nome de "Tertiary_<YYMMDD_HHMMSS>.csv"
'''