#include "mainwindow.h"

MainWindow::MainWindow(QWidget *parent)
    : QMainWindow(parent)
{
    // 1. Instantiate the plot and set it as the main window's central widget
    customPlot = new QCustomPlot(this);
    setCentralWidget(customPlot);
    resize(600, 400);

    // 2. Generate some sample data (a simple quadratic curve)
    QVector<double> x(101), y(101); 
    for (int i = 0; i < 101; ++i)
    {
        x[i] = i / 50.0 - 1;  // x ranges from -1 to 1
        y[i] = x[i] * x[i];   // y = x^2
    }

    // 3. Add a graph to the plot and assign the data
    customPlot->addGraph();
    customPlot->graph(0)->setData(x, y);

    // 4. Label the axes
    customPlot->xAxis->setLabel("X-Axis");
    customPlot->yAxis->setLabel("Y-Axis");

    // 5. Set the axis ranges to ensure the data is fully visible
    customPlot->xAxis->setRange(-1, 1);
    customPlot->yAxis->setRange(0, 1);
}

MainWindow::~MainWindow()
{
}
