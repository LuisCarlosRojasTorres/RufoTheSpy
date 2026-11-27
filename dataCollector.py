'''
Utiliza o SSH para conectar a um ou mais dispositivos, dependendo do número de dispositivos informados. O arquivo config.json deve estar presente e configurado corretamente para que a conexão seja estabelecida com sucesso.
Uma vez con los devices que estiverem conectados vai executar as funções que chamam aos comandos do arquivo config.json:
- getTotalCPUComsumption
- getProcessCPUConsumption
- getMemoryConsumption
- getDiskConsumption
- getThreadsCount
- getKThreadsCount
- getProcessPID

Todos esses comandos sao chamados para cada device a cada "timerSeconds" com uma duração total de "durationHours" horas
Prencher os comandos do arquivo json baseado nos comandos utilizados no arquivo rufo_monitor.py

'''