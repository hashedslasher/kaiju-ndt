#include "mainwindow.h"

MainWindow::MainWindow(QWidget *parent)
    : QMainWindow(parent)
{
    customPlot = new QCustomPlot(this);
    setCentralWidget(customPlot);
    resize(600, 400);

    QVector<double> x(101), y(101); 
    for (int i = 0; i < 101; ++i)
    {
        x[i] = i / 50.0 - 1;  // x ranges from -1 to 1
        y[i] = x[i] * x[i];   // y = x^2
    }

    customPlot->addGraph();
    customPlot->graph(0)->setData(x, y);

    customPlot->xAxis->setLabel("X-Axis");
    customPlot->yAxis->setLabel("Y-Axis");

    customPlot->xAxis->setRange(-1, 1);
    customPlot->yAxis->setRange(0, 1);
}

MainWindow::~MainWindow()
{
}
