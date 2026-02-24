FROM moodlehq/moodle-php-apache:8.3

COPY docker/apache/000-default-ssl.conf /etc/apache2/sites-available/000-default-ssl.conf

# Enable SSL and the SSL vhost
RUN a2enmod ssl \
 && a2ensite 000-default-ssl
