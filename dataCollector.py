'''
Uma vez que os devices estiverem conectados por ssh vai executar as funções que chamam aos comandos do arquivo config.json:
- getTotalCPUComsumption
- getProcessCPUConsumption
- getMemoryConsumption
- getDiskConsumption
- getThreadsCount
- getKThreadsCount
- getProcessPID


Depois de cada chamada os dados são salvos utilizando as funções do módulo dataStorage.py num arquivo csv para cada device (seguindo o mesmo formato e convenção de nome que o arquivo rufo_monitor.py).

Os campos dos comandos do arquivo json estao vazios. Prencher os comandos do arquivo config.json baseado nos comandos utilizados no arquivo rufo_monitor.py

'''