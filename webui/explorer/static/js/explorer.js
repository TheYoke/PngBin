$(document).ready(function() {
    $('.popup-image').magnificPopup({
        type: 'image',
        gallery: {
            enabled: true
        },
        image: {
            titleSrc: function(item) {
                return item.el.text();
            }
        }
    });

    var data = {
        type: 'iframe',
        gallery: {
            enabled: true
        },
        iframe: {
            markup: '<div class="mfp-iframe-scaler">' +
                '<div class="mfp-close"></div>' +
                '<iframe class="mfp-iframe" frameborder="0" allowfullscreen></iframe>' +
                '<div class="mfp-title"></div>' +
                '<div class="mfp-counter"></div>' +
                '</div>'
        },
        callbacks: {
            markupParse: function(template, values, item) {
                values.title = item.el.text() + ' &middot; <a class="source-link" href="' + item.src + '" target="_blank">open original</a>';
            }
        }
    }

    $('.popup-video').magnificPopup(data);
    $('.popup-audio').magnificPopup(data);
    $('.popup-text').magnificPopup(data);
    $('.popup-pdf').magnificPopup(data);

    $('.popup-view-urls').magnificPopup({
        midClick: false,
        items: {
            type: 'inline',
            src: function() {
                var html = '<div class="popup-inline">';
                var items = $('a.file-url');
                if (items.length > 0) {
                    html += '<button class="copy-btn" data-clipboard-action="copy" data-clipboard-target="div#popup-content">Copy All</button>';
                    html += '<div id="popup-content">';
                    for (var i = 0; i < items.length; i++) {
                        html += '<a href="' + items[i].href + '">'  + decodeURIComponent(items[i].href) + '</a><br>';
                    }
                    html += '</div>';
                    html += '<script>new Clipboard(".copy-btn");</script>';
                } else {
                    html += '<h2 style="text-align: center;"> URL Not Found</h2>';
                }
                html += '</div>';
                return html;
            }()
        }
    });

    var data = {
        type:'inline',
        midClick: false,
        callbacks: {
            open: function() {
                var el = $.magnificPopup.instance.st.el[0];
                var btn = $('button.dl-button')[0];
                btn.onclick = function() {
                    window.location.href = el.href + '?dl';
                    btn.innerText = 'Please Wait...';
                    btn.disabled = true;
                }

            },
            close: function() {
                var btn = $('button.dl-button')[0];
                btn.innerText = 'DOWNLOAD';
                btn.disabled = false;
            }
        }
    }

    $('.popup-archive').magnificPopup(data);
    $('.popup-unknown').magnificPopup(data);
});
