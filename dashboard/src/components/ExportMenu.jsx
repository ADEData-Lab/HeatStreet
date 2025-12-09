import React, { useState } from 'react';
import { saveAs } from 'file-saver';
import ExcelJS from 'exceljs';
import jsPDF from 'jspdf';
import html2canvas from 'html2canvas';
import { useDashboard } from '../context/DashboardContext';

async function exportExcel(data) {
  const workbook = new ExcelJS.Workbook();
  const boroughSheet = workbook.addWorksheet('Boroughs');
  boroughSheet.columns = [
    { header: 'Borough', key: 'borough', width: 20 },
    { header: 'EPC', key: 'meanEPC', width: 10 },
    { header: 'Energy', key: 'energy', width: 12 },
    { header: 'Count', key: 'count', width: 12 },
  ];
  (data.boroughData || []).forEach((row) => boroughSheet.addRow(row));

  const scenarioSheet = workbook.addWorksheet('Scenarios');
  scenarioSheet.columns = [
    { header: 'Scenario', key: 'scenario', width: 20 },
    { header: 'Capital (£m)', key: 'capitalCost', width: 15 },
    { header: 'Capex / Property', key: 'costPerProperty', width: 18 },
    { header: 'CO2 Reduction', key: 'co2Reduction', width: 16 },
    { header: 'Bill Savings', key: 'billSavings', width: 16 },
    { header: 'Payback Years', key: 'paybackYears', width: 14 },
  ];
  (data.scenarioData || []).forEach((row) => scenarioSheet.addRow(row));

  const buffer = await workbook.xlsx.writeBuffer();
  saveAs(new Blob([buffer]), 'heat-street-dashboard.xlsx');
}

function exportCSV(data) {
  const headers = ['Borough,Mean EPC,Energy,Count'];
  const rows = (data.boroughData || []).map((row) => `${row.borough},${row.meanEPC},${row.energy},${row.count}`);
  const csv = [...headers, ...rows].join('\n');
  saveAs(new Blob([csv], { type: 'text/csv;charset=utf-8;' }), 'boroughs.csv');
}

async function exportPDF() {
  const root = document.getElementById('dashboard-root') || document.body;
  const canvas = await html2canvas(root, { scale: 1.4, useCORS: true, backgroundColor: '#ffffff' });
  const imgData = canvas.toDataURL('image/png');
  const pdf = new jsPDF('l', 'pt', [canvas.width, canvas.height]);
  pdf.addImage(imgData, 'PNG', 0, 0, canvas.width, canvas.height);
  pdf.save('heat-street-dashboard.pdf');
}

export default function ExportMenu() {
  const { rawData } = useDashboard();
  const [busy, setBusy] = useState(false);

  const handle = async (fn) => {
    setBusy(true);
    try {
      await fn(rawData || {});
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="toolbar export-menu">
      <div className="toolbar-group">
        <span className="toolbar-label">Export</span>
        <div className="button-row">
          <button type="button" onClick={() => saveAs(new Blob([JSON.stringify(rawData || {}, null, 2)]), 'dashboard-data.json')}>
            JSON
          </button>
          <button type="button" onClick={() => handle(exportCSV)} disabled={busy}>
            CSV
          </button>
          <button type="button" onClick={() => handle(exportExcel)} disabled={busy}>
            Excel
          </button>
          <button type="button" onClick={() => handle(exportPDF)} disabled={busy}>
            PDF Snapshot
          </button>
        </div>
      </div>
      {busy && <span className="subtle">Preparing export…</span>}
    </div>
  );
}
