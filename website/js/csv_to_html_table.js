var CsvToHtmlTable = CsvToHtmlTable || {};

CsvToHtmlTable = {
  init: function (options) {
    options = options || {};
    var csv_path = options.csv_path || "";
    var el = options.element || "table-container";
    var allow_download = options.allow_download || false;
    var download_el = options.download_button || "";
    var csv_options = options.csv_options || {};
    var datatables_options = options.datatables_options || {
      paging: false,
      initComplete: function(settings, json) {
        var dataTableWrapper = $(`#${settings.sTableId}_wrapper`);
        var searchInput = dataTableWrapper.find('.dataTables_filter').detach();
        $('#search-container').append(searchInput);
        searchInput.find('input').addClass('form-control').attr('placeholder', 'ex: anti-AQP4');
        searchInput.find('label').contents().unwrap();

        var infoLabel = dataTableWrapper.find('.dataTables_info').detach();
        $('#info-container').append(infoLabel);
      }
    };
    var custom_formatting = options.custom_formatting || [];
    var customTemplates = {};

    $.each(custom_formatting, function (i, v) {
      var colIdx = v[0];
      var func = v[1];
      customTemplates[colIdx] = func;
    });

    var $table = $("<table class='table table-striped table-condensed' id='" + el + "-table'></table>");
    var $containerElement = $("#" + el);
    $containerElement.empty().append($table);

    $.when($.get(csv_path)).then(function (data) {
      var csvData = $.csv.toArrays(data, csv_options);

      var $tableHead = $("<thead></thead>");
      var csvHeaderRow = csvData[0];
      var $tableHeadRow = $("<tr></tr>");
      for (var headerIdx = 0; headerIdx < csvHeaderRow.length; headerIdx++) {
        $tableHeadRow.append($("<th></th>").text(csvHeaderRow[headerIdx]));
      }
      $tableHead.append($tableHeadRow);
      $table.append($tableHead);

      var $tableBody = $("<tbody></tbody>");
      for (var rowIdx = 1; rowIdx < csvData.length; rowIdx++) {
        var rowArr = csvData[rowIdx];
        var $tableBodyRow = $("<tr></tr>");
        for (var colIdx = 0; colIdx < rowArr.length; colIdx++) {
          var $td = $("<td></td>");
          var cellTemplateFunc = customTemplates[colIdx];
          if (cellTemplateFunc) {
            // CHANGED: pass (cell, row, colIdx)
            $td.html(cellTemplateFunc(rowArr[colIdx], rowArr, colIdx));
          } else {
            $td.text(rowArr[colIdx]);
          }
          $tableBodyRow.append($td);
        }
        $tableBody.append($tableBodyRow);
      }
      $table.append($tableBody);

      $table.DataTable(datatables_options);

      if (allow_download) {
        var $downloadButton = $("<a class='btn btn-info' href='" + csv_path + "' download><i class='glyphicon glyphicon-download'></i> Download CSV</a>");
        $("#" + download_el).append($downloadButton);
      }
    });
  }
};

// helpers kept as-is...
function format_link(link) {
  return link ? "<a href='https://hpo.jax.org/app/browse/term/" + link + "' target='_blank'>" + link + "</a>" : "";
}
function disease_link(link) { /* unchanged */ }
function gene_link(genes) { /* unchanged */ }
function ref_link(ref) { /* unchanged */ }
function syn_link(syn) { /* unchanged */ }
