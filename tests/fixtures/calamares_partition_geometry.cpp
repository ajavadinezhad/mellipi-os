#include <kpmcore/core/diskdevice.h>
#include <kpmcore/core/partitiontable.h>
#include "core/PartitionLayout.h"
#include <QApplication>
#include <QLibrary>
#include <iostream>
#include <cstring>
#include <new>
int main(int argc,char**argv){
 QApplication app(argc,argv);
 if(argc!=2)return 3;
 QLibrary plugin(QString::fromLocal8Bit(argv[1]));if(!plugin.load())return 4;
 using Constructor=void(*)(void*,FileSystem::Type,const QString&,const QString&,const QString&,const QString&);
 auto construct=reinterpret_cast<Constructor>(plugin.resolve("_ZN15PartitionLayout14PartitionEntryC1EN10FileSystem4TypeERK7QStringS5_S5_S5_"));if(!construct)return 5;
 DiskDevice d(QStringLiteral("Private geometry fixture"),QStringLiteral("/no-device-opened"),1,1,50331648,512);
 auto gpt=PartitionTable::defaultLastUsable(d,PartitionTable::gpt);
 auto mbr=PartitionTable::defaultLastUsable(d,PartitionTable::msdos);
 if(gpt!=50331614 || mbr!=50331647)return 1;
 alignas(PartitionLayout::PartitionEntry) unsigned char storage[sizeof(PartitionLayout::PartitionEntry)];std::memset(storage,0xa5,sizeof(storage));
 construct(storage,FileSystem::Ext4,QStringLiteral("/"),QStringLiteral("100%"),QString(),QString());
 auto *e=reinterpret_cast<PartitionLayout::PartitionEntry*>(storage);
 if(e->partOnlyPresentWithEncryption)return 2;
 e->~PartitionEntry();
 std::cout<<"{\"GPT_last_usable\":"<<gpt<<",\"MSDOS_last_usable\":"<<mbr<<",\"default_encryption_only\":false}"<<std::endl;
}
