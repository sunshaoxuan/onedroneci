# http site

**start:**  
sudo nginx -c conf_prod/nginx.conf
sudo nginx -c conf_prod/dumi-basic/nginx.conf
sudo nginx -c conf_prod/dumi-nocode/nginx.conf

**check conf files:**  
sudo nginx -c conf_prod/nginx.conf -t
sudo nginx -c conf_prod/dumi-basic/nginx.conf -t
sudo nginx -c conf_prod/dumi-nocode/nginx.conf -t

# https site

**start:**  
sudo nginx -c conf_prod/nginx_https.conf
sudo nginx -c conf_prod/dumi-basic/nginx_https.conf
sudo nginx -c conf_prod/dumi-nocode/nginx_https.conf

**check conf files:**  
sudo nginx -c conf_prod/nginx_https.conf -t
sudo nginx -c conf_prod/dumi-basic/nginx_https.conf -t
sudo nginx -c conf_prod/dumi-nocode/nginx_https.conf -t

## other commands

**check process id and executable path:**  
ps aux | grep nginx

**kill all nginx processes:**  
sudo pkill nginx
sudo killall nginx

**kill process per id:**  
sudo kill -9 <process_id>
