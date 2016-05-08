/***
 *       Filename:  Streamer.h
 *
 *    Description:  Stream table data to a  stream.
 *
 *        Version:  0.0.1
 *        Created:  2016-04-26

 *       Revision:  none
 *
 *         Author:  Dilawar Singh <dilawars@ncbs.res.in>
 *   Organization:  NCBS Bangalore
 *
 *        License:  GNU GPL2
 */

#ifndef  Streamer_INC
#define  Streamer_INC

#define STRINGSTREAM_DOUBLE_PRECISION       10

#include <iostream>
#include <string>
#include <map>
#include <fstream>
#include <sstream>

#include "StreamerBase.h"
#include "Table.h"

using namespace std;

class Streamer
{

public:
    Streamer();
    ~Streamer();

    Streamer& operator=( const Streamer& st );

    string getOutFilepath( void ) const;
    void setOutFilepath( string path );

    string getFormat( void ) const;
    void setFormat( string format );

    size_t getNumTables( void ) const;

    void addTable( Id table );
    void addTables( vector<Id> tables);

    void removeTable( Id table );
    void removeTables( vector<Id> table );

    void zipWithTime( vector<double>& data, double currTime);

    /** Dest functions.
     * The process function called by scheduler on every tick
     */
    void process(const Eref& e, ProcPtr p);

    /**
     * The reinit function called by scheduler for the reset
     */
    void reinit(const Eref& e, ProcPtr p);

    static const Cinfo * initCinfo();

private:

    string outfilePath_ = "";
    string format_ = "csv";
    bool isOutfilePathSet_ = false;

    // dt_ of Table's clock
    vector<double> tableDt_;

    // This currTime is not computed using the ProcPtr but rather using Tables
    // dt_ and number of entries written.
    double currTime_ = 0.0;

    // Used for adding or removing tables
    vector<Id> tableIds_;
    vector<Table*> tables_;
    vector<string> columns_ = { "time" };            /* Keep tabe names. */

    /*  Keep data in vector */
    vector<double> data_;

};

#endif   /* ----- #ifndef Streamer_INC  ----- */
