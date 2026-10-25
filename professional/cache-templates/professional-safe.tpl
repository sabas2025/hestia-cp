# HESTIA_PRO_BUSINESS_V1
# Public response cache; opt in per domain and validate application behavior.
#=========================================================================#
# Default Web Domain Template                                             #
# DO NOT MODIFY THIS FILE! CHANGES WILL BE LOST WHEN REBUILDING DOMAINS   #
# https://hestiacp.com/docs/server-administration/web-templates.html      #
#=========================================================================#

server {
	listen      %ip%:%proxy_port%;
	server_name %domain_idn% %alias_idn%;
	error_log   /var/log/%web_system%/domains/%domain%.error.log error;

	include %home%/%user%/conf/web/%domain%/nginx.forcessl.conf*;

	location ~ /\.(?!well-known\/) {
		deny all;
		return 404;
	}

	location / {
		proxy_pass http://%ip%:%web_port%;

		proxy_cache hpro_%domain%;
		proxy_cache_valid 200 60s;
		proxy_cache_bypass $no_cache $http_authorization;
		proxy_no_cache $no_cache $http_authorization $upstream_http_set_cookie;
		proxy_cache_lock on;
		proxy_cache_key "$scheme$request_method$host$request_uri";
		add_header X-Hestia-Cache $upstream_cache_status always;

		set $no_cache 0;
        if ($request_method !~ ^(GET|HEAD)$) { set $no_cache 1; }
        if ($http_cookie != "") { set $no_cache 1; }
        if ($http_authorization != "") { set $no_cache 1; }
        if ($args != "") { set $no_cache 1; }
        if ($uri ~* "^/(api|oauth|callback|webhook|login|logout|admin|account|cart|checkout|pedido|cliente|crm|hub)(/|[?.]|$)") { set $no_cache 1; }

		if ($request_uri ~* "/wp-admin/|/wp-json/|wp-.*.php|xmlrpc.php|/store.*|/cart.*|/my-account.*|/checkout.*|/user/|/admin/|/administrator/|/manager/|index.php") {
			set $no_cache 1;
		}

		if ($http_cookie ~* "comment_author|wordpress_[a-f0-9]+|wp-postpass|wordpress_no_cache|wordpress_logged_in|woocommerce_items_in_cart|woocommerce_cart_hash|PHPSESSID") {
			set $no_cache 1;
		}

		if ($http_cookie ~ SESS) {
			set $no_cache 1;
		}

		location ~* ^.+\.(%proxy_extensions%)$ {
			try_files   $uri @fallback;

			root        %docroot%;
			access_log  /var/log/%web_system%/domains/%domain%.log combined;
			access_log  /var/log/%web_system%/domains/%domain%.bytes bytes;

			expires     max;

			proxy_cache off;
		}
	}

	location @fallback {
		proxy_pass http://%ip%:%web_port%;
	}

	location /error/ {
		alias %home%/%user%/web/%domain%/document_errors/;
	}

	include %home%/%user%/conf/web/%domain%/nginx.conf_*;
}
