"""The tape layer: price, volatility, options, setups, ladder, catalysts.

Everything here is context. Nothing here is a criterion, nothing here can move a
criterion's status, and nothing here says buy or sell. Every setup carries a long
read and a short read; a trailing bias audit counts which way the labels lean so
drift in the detection thresholds is visible.

    spcx tape        fetch bars + options, measure, write data/tape.json
    spcx dashboard   render site/tape.html from data/latest.json + data/tape.json
"""
