# http site

**restart:**  
sudo pkill nginx && sudo /usr/sbin/nginx -c conf_prod/nginx.conf

**start:**  
sudo /usr/sbin/nginx -c conf_prod/nginx.conf
sudo /usr/sbin/nginx -c conf_prod/dumi-basic/nginx.conf
sudo /usr/sbin/nginx -c conf_prod/dumi-nocode/nginx.conf

**check conf files:**  
sudo /usr/sbin/nginx -c conf_prod/nginx.conf -t
sudo /usr/sbin/nginx -c conf_prod/dumi-basic/nginx.conf -t
sudo /usr/sbin/nginx -c conf_prod/dumi-nocode/nginx.conf -t

# https site

**start:**  
sudo /usr/sbin/nginx -c conf_prod/nginx_https.conf
sudo /usr/sbin/nginx -c conf_prod/dumi-basic/nginx_https.conf
sudo /usr/sbin/nginx -c conf_prod/dumi-nocode/nginx_https.conf

**check conf files:**  
sudo /usr/sbin/nginx -c conf_prod/nginx_https.conf -t
sudo /usr/sbin/nginx -c conf_prod/dumi-basic/nginx_https.conf -t
sudo /usr/sbin/nginx -c conf_prod/dumi-nocode/nginx_https.conf -t

## other commands

**check process id and executable path:**  
ps aux | grep nginx

**kill all nginx processes:**  
sudo pkill nginx
sudo killall nginx

**kill process per id:**  
sudo kill -9 <process_id>

**check nginx logs:**  
Copy logs to host machine:
sudo docker cp <container_id>:/usr/local/openresty/nginx/logs ./nginx-logs

Stream logs:
sudo docker exec -it <container_id> tail -f /usr/local/openresty/nginx/logs/error.log
