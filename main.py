'''
esta componente 
1. starta a aplicação que é o UI web para o usuário, que inicializa no localhost porta 2402. 
2. Na Ui vai ter checkbox para selecionar Primary, Secondary e Tertiary, e um botão para iniciar a coleta de dados, e pausar.
3. Ele chama o sshConnector.py para conectar os devices informados no arquivo config.json.
4. Ele chama o dataCollector.py para coletar os dados dos devices conectados.
5. Todos esses comandos sao chamados para cada device a cada "timerSeconds" com uma duração total de "durationHours" horas
6. Uma vez que os dados sao coletados, ele chama o dataStorage.py para armazenar os dados coletados em um arquivo .csv, e esse arquivo tem que ser criado caso não exista, e caso exista ele tem que ser atualizado com os novos dados coletados.
7. Alem da seleção de devices a conectar. Embaixo vai ter 3 colunas e duas filas de graficos xy para Primary, Secondary e Tertiary como colunas. 
8. na primera file vai ter titulo CPU usage, onde vai ter consumo do cpu total e pelo processo customProcess, e na segunda file vai ter titulo Memory usage, onde vai ter consumo de memoria total 
9. Embaixo da segunda fila vai ter labels para threads count e kthreads count, e embaixo vai ter labels para disk usage e process PID.
10. A cada "timerSeconds" os graficos vao ser atualizados com os novos dados
11. A cada "timerSeconds" os labels vao ser atualizados com os novos dados
12. Cuando chegar no tempo de "durationHours" a coleta de dados vai ser pausada e os graficos e labels vao parar de ser atualizados. Imagens vao ser salvas na pasta output com o nome do device conectado e a data e hora da coleta de dados, e os arquivos .csv vao ser salvos na pasta output com o nome do device conectado e a data e hora da coleta de dados.
'''