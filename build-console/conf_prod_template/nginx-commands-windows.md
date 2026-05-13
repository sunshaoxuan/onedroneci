# http site

**start:**  
nginx -c conf_prod\nginx.conf
nginx -c conf_prod\dumi-basic\nginx.conf
nginx -c conf_prod\dumi-nocode\nginx.conf

**check conf files:**  
nginx -c conf_prod\nginx.conf -t
nginx -c conf_prod\dumi-basic\nginx.conf -t
nginx -c conf_prod\dumi-nocode\nginx.conf -t

# https site

**start:**  
nginx -c conf_prod\nginx_https.conf
nginx -c conf_prod\dumi-basic\nginx_https.conf
nginx -c conf_prod\dumi-nocode\nginx_https.conf

**check conf files:**  
nginx -c conf_prod\nginx_https.conf -t
nginx -c conf_prod\dumi-basic\nginx_https.conf -t
nginx -c conf_prod\dumi-nocode\nginx_https.conf -t

## other commands

**check process id and executable path:**  
wmic process where "name='nginx.exe'" get ProcessId,ExecutablePath,CommandLine

**kill all nginx processes:**  
taskkill /F /IM nginx.exe

**kill process per id:**  
taskkill /F /PID <process_id>
