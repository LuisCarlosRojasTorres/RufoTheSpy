'''
Este componente conecta atraves de SSH ate 3 Ips diferentes ao mesmo tempo, estes são Primary, Secondary e Tertiary.
Para ser utilizado é necessario o arquivo config.json e que o componentes que o utilize tem que informar quantos devices vao ser conectados.
Se o numOfDevices for informado for 1, apenas o Primary sera conectado, se for 2, o Primary e Secondary serao conectados e se for 3, todos os 3 serao conectados.
Entao tem que ter :
- Uma função para conectar os n devices que forem informados, e essa função tem que retornar uma lista de objetos SSHClient, cada um conectado a um device diferente.
- Uma função para desconectar os n devices que forem informados, e essa função tem que receber uma lista de objetos SSHClient, cada um conectado a um device diferente.
- Tem que ter tratamento de erros para que o fato de um device nao estar disponivel nao impeça que os outros devices sejam conectados.
'''